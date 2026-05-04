"""Tenant-scoped workflow CRUD + /run + /runs endpoints.

Mirrors routers/prompts.py for session/principal handling.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.auth.principal import Principal, resolve_principal
from control_plane.errors import APIError, api_error, not_found
from control_plane.models_db import (
    containers,
    prompts,
    workflow_events,
    workflow_runs,
    workflows,
)
from control_plane.schemas import (
    CreateWorkflowRequest,
    RunWorkflowRequest,
    UpdateWorkflowRequest,
)
from control_plane.sse import format_sse, should_forward
from control_plane.workflow_engine import start_run
from control_plane.workflows_service import (
    build_workflow_row,
    run_detail_view,
    run_view,
    validate_workflow_fields,
    workflow_view,
)

router = APIRouter()

_WF_COLS = [
    workflows.c.id,
    workflows.c.tenant_id,
    workflows.c.name,
    workflows.c.description,
    workflows.c.steps,
    workflows.c.created_by,
    workflows.c.created_at,
    workflows.c.updated_at,
]


async def _load_owned_workflow(
    session: AsyncSession, tenant_id: str, wid: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(*_WF_COLS).where(
                workflows.c.id == wid, workflows.c.tenant_id == tenant_id
            )
        )
    ).mappings().first()
    if row is None:
        raise not_found("workflow not found")
    return dict(row)


async def _assert_steps_exist(
    session: AsyncSession, tenant_id: str, steps: list[dict[str, Any]]
) -> None:
    """Every referenced prompt and container must belong to the tenant."""
    pids = {s["prompt_id"] for s in steps}
    cids = {s["container_id"] for s in steps}
    have_p = {
        r[0]
        for r in (
            await session.execute(
                select(prompts.c.id).where(
                    prompts.c.id.in_(pids), prompts.c.tenant_id == tenant_id
                )
            )
        ).all()
    }
    missing_p = pids - have_p
    if missing_p:
        raise api_error(
            400, "validation_error", f"unknown prompt(s): {sorted(missing_p)}", "steps"
        )
    have_c = {
        r[0]
        for r in (
            await session.execute(
                select(containers.c.id).where(
                    containers.c.id.in_(cids), containers.c.tenant_id == tenant_id
                )
            )
        ).all()
    }
    missing_c = cids - have_c
    if missing_c:
        raise api_error(
            400, "validation_error", f"unknown container(s): {sorted(missing_c)}", "steps"
        )


async def _load_run(
    session: AsyncSession, tenant_id: str, rid: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(workflow_runs).where(
                workflow_runs.c.id == rid, workflow_runs.c.tenant_id == tenant_id
            )
        )
    ).mappings().first()
    return dict(row) if row is not None else None


@router.get("/workflows")
async def list_workflows(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        rows = (
            await session.execute(
                select(*_WF_COLS)
                .where(workflows.c.tenant_id == principal.tenant_id)
                .order_by(workflows.c.name)
            )
        ).mappings().all()
    return {"workflows": [workflow_view(dict(r)) for r in rows]}


@router.post("/workflows")
async def create_workflow(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "workflows are tenant-scoped")
    payload = CreateWorkflowRequest(**(await request.json()))
    steps = validate_workflow_fields(
        name=payload.name,
        description=payload.description,
        steps=[s.model_dump() for s in payload.steps],
    )
    async with request.app.state.session_factory() as session:
        await _assert_steps_exist(session, principal.tenant_id, steps)
        dupe = (
            await session.execute(
                select(workflows.c.id).where(
                    workflows.c.tenant_id == principal.tenant_id,
                    workflows.c.name == payload.name.strip(),
                )
            )
        ).first()
        if dupe is not None:
            raise api_error(
                409,
                "conflict",
                f"a workflow named {payload.name.strip()!r} already exists",
                "name",
            )
        row = build_workflow_row(
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            name=payload.name,
            description=payload.description,
            steps=steps,
        )
        await session.execute(workflows.insert().values(**row))
        await session.commit()
    return workflow_view(row)


@router.get("/workflows/{wid}")
async def get_workflow(
    wid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        return workflow_view(
            await _load_owned_workflow(session, principal.tenant_id, wid)
        )


@router.patch("/workflows/{wid}")
async def patch_workflow(
    wid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    patch = UpdateWorkflowRequest(**(await request.json()))
    async with request.app.state.session_factory() as session:
        existing = await _load_owned_workflow(session, principal.tenant_id, wid)
        name = patch.name if patch.name is not None else existing["name"]
        description = (
            patch.description if patch.description is not None else existing.get("description")
        )
        raw_steps = (
            [s.model_dump() for s in patch.steps]
            if patch.steps is not None
            else existing["steps"]
        )
        steps = validate_workflow_fields(name=name, description=description, steps=raw_steps)
        if patch.steps is not None:
            await _assert_steps_exist(session, principal.tenant_id, steps)
        if name.strip() != existing["name"]:
            dupe = (
                await session.execute(
                    select(workflows.c.id).where(
                        workflows.c.tenant_id == principal.tenant_id,
                        workflows.c.name == name.strip(),
                        workflows.c.id != wid,
                    )
                )
            ).first()
            if dupe is not None:
                raise api_error(
                    409,
                    "conflict",
                    f"a workflow named {name.strip()!r} already exists",
                    "name",
                )
        values = {
            "name": name.strip(),
            "description": description,
            "steps": steps,
            "updated_at": datetime.now(UTC),
        }
        await session.execute(
            workflows.update()
            .where(
                workflows.c.id == wid, workflows.c.tenant_id == principal.tenant_id
            )
            .values(**values)
        )
        await session.commit()
        existing.update(values)
    return workflow_view(existing)


@router.delete("/workflows/{wid}", status_code=204)
async def delete_workflow(
    wid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> None:
    async with request.app.state.session_factory() as session:
        await _load_owned_workflow(session, principal.tenant_id, wid)
        await session.execute(
            sa.delete(workflows).where(
                workflows.c.id == wid, workflows.c.tenant_id == principal.tenant_id
            )
        )
        await session.commit()


@router.post("/workflows/{wid}/run")
async def run_workflow(
    wid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    body = await request.body()
    payload = RunWorkflowRequest(**(await request.json() if body else {}))
    st = request.app.state
    async with st.session_factory() as session:
        workflow = await _load_owned_workflow(session, principal.tenant_id, wid)
        try:
            run_id = await start_run(
                session,
                settings=st.settings,
                session_factory=st.session_factory,
                docker_client=getattr(st, "docker_client", None),
                shim_dispatcher=getattr(st, "shim", None),
                tenant_id=principal.tenant_id,
                workflow=workflow,
                trigger_source=payload.trigger_source,
            )
        except APIError:
            # Let validation/not-found errors from before submit propagate normally.
            raise
        except Exception as exc:
            # A submit failure (container can't start, no credential, admission
            # denied) — return a clean error envelope instead of a 500.
            raise api_error(
                502,
                "workflow_start_failed",
                str(exc),
            ) from exc
        run = await _load_run(session, principal.tenant_id, run_id)
    return run_view(run)


@router.get("/workflows/{wid}/runs")
async def list_workflow_runs(
    wid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        await _load_owned_workflow(session, principal.tenant_id, wid)
        rows = (
            await session.execute(
                select(workflow_runs)
                .where(
                    workflow_runs.c.workflow_id == wid,
                    workflow_runs.c.tenant_id == principal.tenant_id,
                )
                .order_by(workflow_runs.c.started_at.desc())
                .limit(100)
            )
        ).mappings().all()
    return {"runs": [run_view(dict(r)) for r in rows]}


@router.get("/workflows/{wid}/runs/{run_id}")
async def get_workflow_run(
    wid: str,
    run_id: str,
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        await _load_owned_workflow(session, principal.tenant_id, wid)
        run = await _load_run(session, principal.tenant_id, run_id)
        if run is None or run["workflow_id"] != wid:
            raise not_found("workflow run not found")
        return run_detail_view(run)


def _serialize_event(r: Any) -> dict[str, Any]:
    return {"seq": r.seq, "type": r.type, "ts": r.ts.isoformat(), "payload": r.payload}


async def _fetch_events(session_factory: Any, run_id: str, after_seq: int | None) -> list[Any]:
    async with session_factory() as s:
        rows = (
            await s.execute(
                select(workflow_events)
                .where(workflow_events.c.run_id == run_id)
                .order_by(workflow_events.c.seq.asc())
            )
        ).all()
    return [r for r in rows if should_forward(seq=int(r.seq), after_seq=after_seq)]


async def _workflow_events_stream(
    session_factory: Any,
    run_id: str,
    after_seq: int | None,
    is_disconnected: Any,
    poll_interval: float = 1.5,
) -> Any:
    """Tail workflow_events for a run over SSE.

    There is no upstream socket (unlike task events), so we poll the table:
    emit the backlog after `after_seq`, then poll for newer seqs until a
    terminal (completed/failed) frame is sent or the client disconnects. Each
    poll uses a fresh short-lived session so no DB connection is held across
    the sleep (avoids SSE pool exhaustion)."""
    last_seq = after_seq
    terminal_seen = False
    while not terminal_seen:
        if await is_disconnected():
            return
        rows = await _fetch_events(session_factory, run_id, last_seq)
        for r in rows:
            yield format_sse(json.dumps(_serialize_event(r)))
            last_seq = int(r.seq)
            if r.type in ("completed", "failed"):
                terminal_seen = True
        if terminal_seen:
            return
        await asyncio.sleep(poll_interval)


@router.get("/workflows/{wid}/runs/{run_id}/events", response_model=None)
async def stream_workflow_run_events(
    wid: str,
    run_id: str,
    request: Request,
    principal: Principal = Depends(resolve_principal),
    after_seq: int | None = None,
) -> StreamingResponse | dict[str, Any]:
    async with request.app.state.session_factory() as session:
        await _load_owned_workflow(session, principal.tenant_id, wid)
        run = await _load_run(session, principal.tenant_id, run_id)
        if run is None or run["workflow_id"] != wid:
            raise not_found("workflow run not found")

    factory = request.app.state.session_factory
    accept = request.headers.get("accept", "")
    if "text/event-stream" not in accept:
        rows = await _fetch_events(factory, run_id, after_seq)
        return {"events": [_serialize_event(r) for r in rows]}

    async def _is_disconnected() -> bool:
        return await request.is_disconnected()

    return StreamingResponse(
        _workflow_events_stream(factory, run_id, after_seq, _is_disconnected),
        media_type="text/event-stream",
    )
