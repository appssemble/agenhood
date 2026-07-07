"""Tenant-scoped scheduled-tasks CRUD on /v1/scheduled-tasks.

Mirrors routers/workflows.py / routers/prompts.py for session/principal handling.
A schedule fires a polymorphic ``target`` (prompt or workflow); the legacy
container-scoped compatibility routes live at the bottom of this file (Task 20).
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.auth.principal import Principal, resolve_principal
from control_plane.errors import APIError, api_error, not_found
from control_plane.ids import new_prompt_id, new_scheduled_task_id
from control_plane.models_db import containers, prompts, scheduled_tasks, workflows
from control_plane.scheduled_target import validate_target
from control_plane.scheduling import compute_next_run, validate_schedule
from control_plane.schemas import (
    CreateScheduledTaskRequest,
    ScheduledTaskOut,
    UpdateScheduledTaskRequest,
)

_LEGACY_SUNSET = "Sat, 01 Aug 2026 00:00:00 GMT"

router = APIRouter(tags=["Scheduled Tasks"])


class ScheduledTaskListResponse(BaseModel):
    """Envelope returned by ``GET /scheduled-tasks``."""

    scheduled_tasks: list[ScheduledTaskOut] = Field(
        description="The calling tenant's scheduled tasks, newest first."
    )

_ST_COLS = [
    scheduled_tasks.c.id,
    scheduled_tasks.c.tenant_id,
    scheduled_tasks.c.name,
    scheduled_tasks.c.target,
    scheduled_tasks.c.schedule,
    scheduled_tasks.c.timezone,
    scheduled_tasks.c.enabled,
    scheduled_tasks.c.next_run_at,
    scheduled_tasks.c.last_run_at,
    scheduled_tasks.c.last_run_ref,
    scheduled_tasks.c.last_status,
    scheduled_tasks.c.created_at,
]


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _row_to_out(row: dict[str, Any]) -> ScheduledTaskOut:
    created = row["created_at"]
    return ScheduledTaskOut(
        id=row["id"],
        name=row["name"],
        target=row["target"],
        schedule=row["schedule"],
        timezone=row["timezone"],
        enabled=row["enabled"],
        next_run_at=_iso(row["next_run_at"]),
        last_run_at=_iso(row["last_run_at"]),
        last_run_ref=row["last_run_ref"],
        last_status=row["last_status"],
        created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
    )


def _resolve_next_run(schedule: dict, timezone: str, run_at: str | None) -> datetime | None:
    """Initial next_run_at: parse run_at for 'once', compute for recurring."""
    validate_schedule(schedule, timezone)
    if schedule.get("kind") == "once":
        if not run_at:
            raise APIError(
                400,
                "validation_error",
                "run_at is required for a one-time schedule (provide a new run_at to "
                "re-enable)",
                "run_at",
            )
        try:
            parsed = datetime.fromisoformat(run_at)
        except ValueError as exc:
            raise APIError(400, "validation_error", "run_at must be ISO-8601", "run_at") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return compute_next_run(schedule, timezone, datetime.now(UTC))


async def _assert_target_exists(
    session: AsyncSession, tenant_id: str, target: dict[str, Any]
) -> None:
    """The schedule's referenced prompt/container/workflow must belong to the tenant."""
    if target["kind"] == "prompt":
        have_p = (
            await session.execute(
                select(prompts.c.id).where(
                    prompts.c.id == target["prompt_id"],
                    prompts.c.tenant_id == tenant_id,
                )
            )
        ).first()
        if have_p is None:
            raise api_error(
                400, "validation_error", f"unknown prompt: {target['prompt_id']}", "target"
            )
        have_c = (
            await session.execute(
                select(containers.c.id).where(
                    containers.c.id == target["container_id"],
                    containers.c.tenant_id == tenant_id,
                )
            )
        ).first()
        if have_c is None:
            raise api_error(
                400, "validation_error", f"unknown container: {target['container_id']}", "target"
            )
        return
    # kind == "workflow"
    have_w = (
        await session.execute(
            select(workflows.c.id).where(
                workflows.c.id == target["workflow_id"],
                workflows.c.tenant_id == tenant_id,
            )
        )
    ).first()
    if have_w is None:
        raise api_error(
            400, "validation_error", f"unknown workflow: {target['workflow_id']}", "target"
        )


async def _load_owned_schedule(
    session: AsyncSession, tenant_id: str, sid: str
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(*_ST_COLS).where(
                scheduled_tasks.c.id == sid,
                scheduled_tasks.c.tenant_id == tenant_id,
            )
        )
    ).mappings().first()
    if row is None:
        raise not_found(f"scheduled task {sid} not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Shared create/update helpers — single source of truth for the row logic.
# Both the tenant-scoped handlers and the legacy adapters call these.
# ---------------------------------------------------------------------------


async def _do_create_scheduled_task(
    session: AsyncSession,
    *,
    tenant_id: str,
    name: str,
    target: dict[str, Any],  # already validated via validate_target()
    schedule: dict[str, Any],
    timezone: str,
    run_at: str | None,
) -> dict[str, Any]:
    """Insert a new scheduled-task row and return its serialised output dict."""
    await _assert_target_exists(session, tenant_id, target)
    try:
        next_run_at = _resolve_next_run(schedule, timezone, run_at)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "schedule") from exc

    now = datetime.now(UTC)
    sid = new_scheduled_task_id()
    row: dict[str, Any] = {
        "id": sid,
        "tenant_id": tenant_id,
        "name": name,
        "target": target,
        "schedule": schedule,
        "timezone": timezone,
        "enabled": True,
        "next_run_at": next_run_at,
        "last_run_at": None,
        "last_run_ref": None,
        "last_status": None,
        "created_at": now,
        "updated_at": now,
    }
    await session.execute(scheduled_tasks.insert().values(**row))
    await session.commit()
    return _row_to_out(row).model_dump()


async def _do_update_scheduled_task(
    session: AsyncSession,
    *,
    tenant_id: str,
    sid: str,
    existing: dict[str, Any],
    values: dict[str, Any],
    schedule: dict[str, Any],
    timezone: str,
    run_at: str | None,
    recompute: bool,
) -> dict[str, Any]:
    """Apply ``values`` to the scheduled-task row and return the merged output dict.

    ``values`` is the pre-assembled patch dict (name, target, enabled, schedule,
    timezone, updated_at, …).  ``schedule`` and ``timezone`` are the *effective*
    values after merging patch over existing; ``recompute`` signals that
    next_run_at must be recalculated.
    """
    if recompute:
        try:
            values["next_run_at"] = _resolve_next_run(schedule, timezone, run_at)
        except ValueError as exc:
            raise api_error(400, "validation_error", str(exc), "schedule") from exc
    if values.get("enabled") is False:
        values["next_run_at"] = None

    await session.execute(
        scheduled_tasks.update()
        .where(
            scheduled_tasks.c.id == sid,
            scheduled_tasks.c.tenant_id == tenant_id,
        )
        .values(**values)
    )
    await session.commit()
    existing.update(values)
    return _row_to_out(existing).model_dump()


@router.get("/scheduled-tasks", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """List the calling tenant's scheduled tasks (newest first).

    Requires a tenant-scoped bearer token. Returns every schedule owned by the
    principal's tenant, ordered by creation time descending.
    """
    async with request.app.state.session_factory() as session:
        rows = (
            await session.execute(
                select(*_ST_COLS)
                .where(scheduled_tasks.c.tenant_id == principal.tenant_id)
                .order_by(scheduled_tasks.c.created_at.desc())
            )
        ).mappings().all()
    return {"scheduled_tasks": [_row_to_out(dict(r)).model_dump() for r in rows]}


@router.post("/scheduled-tasks", status_code=200, response_model=ScheduledTaskOut)
async def create_scheduled_task(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """Create a scheduled task for the calling tenant.

    Requires a tenant-scoped bearer token; staff principals (``tenant_id`` is
    None) are rejected with 403 `forbidden`. Body is a
    `CreateScheduledTaskRequest`. The schedule/timezone are validated (400
    `validation_error` on failure) and the polymorphic `target` (prompt or
    workflow) must reference resources that belong to the tenant (400
    `validation_error`). One-time (`kind: once`) schedules require a valid
    `run_at`. Returns the created schedule with HTTP 200.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "scheduled tasks are tenant-scoped")
    payload = CreateScheduledTaskRequest(**(await request.json()))

    # Validate early (before opening a DB connection) so callers get a fast 400.
    try:
        validate_schedule(payload.schedule, payload.timezone)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "schedule") from exc
    target = validate_target(payload.target)

    async with request.app.state.session_factory() as session:
        return await _do_create_scheduled_task(
            session,
            tenant_id=principal.tenant_id,
            name=payload.name,
            target=target,
            schedule=payload.schedule,
            timezone=payload.timezone,
            run_at=payload.run_at,
        )


@router.get("/scheduled-tasks/{sid}", response_model=ScheduledTaskOut)
async def get_scheduled_task(
    sid: Annotated[str, Path(description="Scheduled-task id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Fetch a single scheduled task by id.

    Requires a tenant-scoped bearer token. Returns 404 `not_found` if no
    schedule with ``sid`` belongs to the tenant.
    """
    async with request.app.state.session_factory() as session:
        return _row_to_out(
            await _load_owned_schedule(session, principal.tenant_id, sid)
        ).model_dump()


@router.patch("/scheduled-tasks/{sid}", response_model=ScheduledTaskOut)
async def update_scheduled_task(
    sid: Annotated[str, Path(description="Scheduled-task id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Update a scheduled task's name, target, schedule, timezone, or enabled flag.

    Requires a tenant-scoped bearer token. Body is an
    `UpdateScheduledTaskRequest`; omitted fields are left unchanged. Returns 404
    `not_found` if the schedule is not found for the tenant. A replacement
    `target` must reference tenant-owned resources (400 `validation_error`).
    `next_run_at` is recomputed when the schedule, timezone, or `run_at`
    changes, or when re-enabling a disabled schedule; disabling clears
    `next_run_at`. Invalid schedules return 400 `validation_error`.
    """
    patch = UpdateScheduledTaskRequest(**(await request.json()))
    async with request.app.state.session_factory() as session:
        existing = await _load_owned_schedule(session, principal.tenant_id, sid)

        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if patch.name is not None:
            values["name"] = patch.name
        if patch.target is not None:
            target = validate_target(patch.target)
            await _assert_target_exists(session, principal.tenant_id, target)
            values["target"] = target
        if patch.enabled is not None:
            values["enabled"] = patch.enabled

        # Effective schedule/timezone after merging patch over existing.
        schedule = patch.schedule if patch.schedule is not None else existing["schedule"]
        timezone = patch.timezone if patch.timezone is not None else existing["timezone"]
        recompute = (
            patch.schedule is not None
            or patch.timezone is not None
            or patch.run_at is not None
            or (patch.enabled is True and not existing["enabled"])
        )
        if patch.schedule is not None:
            values["schedule"] = patch.schedule
        if patch.timezone is not None:
            values["timezone"] = timezone

        return await _do_update_scheduled_task(
            session,
            tenant_id=principal.tenant_id,
            sid=sid,
            existing=existing,
            values=values,
            schedule=schedule,
            timezone=timezone,
            run_at=patch.run_at,
            recompute=recompute,
        )


@router.delete("/scheduled-tasks/{sid}", status_code=204)
async def delete_scheduled_task(
    sid: Annotated[str, Path(description="Scheduled-task id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> None:
    """Delete a scheduled task; returns 204 No Content on success.

    Requires a tenant-scoped bearer token. Returns 404 `not_found` if the
    schedule does not exist for the tenant.
    """
    async with request.app.state.session_factory() as session:
        await _load_owned_schedule(session, principal.tenant_id, sid)
        await session.execute(
            sa.delete(scheduled_tasks).where(
                scheduled_tasks.c.id == sid,
                scheduled_tasks.c.tenant_id == principal.tenant_id,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Legacy container-scoped compatibility adapters (Task 20)
# These thin wrappers bridge the OLD /v1/containers/{cid}/scheduled-tasks*
# paths that were removed when Task 18 introduced tenant-scoped routes.
# They are intentionally deprecated and will be removed after the Sunset date.
# ---------------------------------------------------------------------------


@router.get("/containers/{cid}/scheduled-tasks")
async def legacy_list_scheduled_tasks(
    cid: Annotated[
        str, Path(description="Container id (legacy path segment; ignored on redirect).")
    ],
) -> RedirectResponse:
    """Deprecated: 308-redirect to the tenant-scoped list endpoint.

    Legacy container-scoped route (Task 20). Issues a 308 Permanent Redirect to
    `GET /v1/scheduled-tasks`. Deprecated and slated for removal after the
    Sunset date; prefer the tenant-scoped route.
    """
    return RedirectResponse(url="/v1/scheduled-tasks", status_code=308)


@router.get("/containers/{cid}/scheduled-tasks/{sid}")
async def legacy_get_scheduled_task(
    cid: Annotated[
        str, Path(description="Container id (legacy path segment; ignored on redirect).")
    ],
    sid: Annotated[str, Path(description="Scheduled-task id.")],
) -> RedirectResponse:
    """Deprecated: 308-redirect to the tenant-scoped get endpoint.

    Legacy container-scoped route (Task 20). Issues a 308 Permanent Redirect to
    `GET /v1/scheduled-tasks/{sid}`. Deprecated and slated for removal after the
    Sunset date.
    """
    return RedirectResponse(url=f"/v1/scheduled-tasks/{sid}", status_code=308)


@router.delete("/containers/{cid}/scheduled-tasks/{sid}")
async def legacy_delete_scheduled_task(
    cid: Annotated[
        str, Path(description="Container id (legacy path segment; ignored on redirect).")
    ],
    sid: Annotated[str, Path(description="Scheduled-task id.")],
) -> RedirectResponse:
    """Deprecated: 308-redirect to the tenant-scoped delete endpoint.

    Legacy container-scoped route (Task 20). Issues a 308 Permanent Redirect to
    `DELETE /v1/scheduled-tasks/{sid}`. Deprecated and slated for removal after
    the Sunset date.
    """
    return RedirectResponse(url=f"/v1/scheduled-tasks/{sid}", status_code=308)


async def _create_adhoc_prompt(
    session: AsyncSession,
    tenant_id: str,
    name: str,
    prompt_text: str,
    user_id: str | None,
) -> str:
    """Insert an ad-hoc prompt and return its new ID.

    Appends a uuid hex suffix to the name if a prompt with the base name
    already exists in the tenant (avoids idx_prompts_tenant_name violations).
    """
    prompt_name = f"(adhoc) {name}"
    existing = (
        await session.execute(
            select(prompts.c.id).where(
                prompts.c.tenant_id == tenant_id,
                prompts.c.name == prompt_name,
            )
        )
    ).first()
    if existing is not None:
        prompt_name = f"(adhoc) {name} {_uuid.uuid4().hex[:8]}"

    pid = new_prompt_id()
    now = datetime.now(UTC)
    await session.execute(
        prompts.insert().values(
            id=pid,
            tenant_id=tenant_id,
            name=prompt_name,
            body=prompt_text,
            tags=[],
            variables=[],
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
    )
    return pid


def _legacy_headers(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = _LEGACY_SUNSET


@router.post(
    "/containers/{cid}/scheduled-tasks",
    status_code=200,
    response_model=ScheduledTaskOut,
)
async def legacy_create_scheduled_task(
    cid: Annotated[str, Path(description="Container the ad-hoc prompt/schedule is bound to.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> Response:
    """Deprecated: create a schedule from the old container-scoped body.

    Legacy container-scoped route (Task 20). Requires a tenant-scoped bearer
    token; staff principals (``tenant_id`` is None) get 403 `forbidden`. Old
    body shape: `{name, task_body:{prompt,...}, schedule, timezone, run_at?}`.
    Creates an ad-hoc prompt from ``task_body["prompt"]`` (bound to ``cid``) and
    delegates to the shared create helper, which validates and inserts (400
    `validation_error` on a bad schedule/target). Returns the created schedule
    (HTTP 200) with `Deprecation`/`Sunset` response headers.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "scheduled tasks are tenant-scoped")

    payload = await request.json()
    name: str = payload.get("name", "")
    task_body: dict[str, Any] = payload.get("task_body") or {}
    prompt_text: str = task_body.get("prompt", "")
    schedule: dict[str, Any] = payload.get("schedule") or {}
    timezone: str = payload.get("timezone", "UTC")
    run_at: str | None = payload.get("run_at")

    # Note: validate_schedule is NOT called here — _do_create_scheduled_task
    # calls _resolve_next_run which validates once on the happy path.
    async with request.app.state.session_factory() as session:
        pid = await _create_adhoc_prompt(
            session, principal.tenant_id, name, prompt_text, principal.user_id
        )
        target = validate_target(
            {"kind": "prompt", "container_id": cid, "prompt_id": pid, "variables": {}}
        )
        result = await _do_create_scheduled_task(
            session,
            tenant_id=principal.tenant_id,
            name=name,
            target=target,
            schedule=schedule,
            timezone=timezone,
            run_at=run_at,
        )

    resp = JSONResponse(result)
    _legacy_headers(resp)
    return resp


@router.patch(
    "/containers/{cid}/scheduled-tasks/{sid}",
    status_code=200,
    response_model=ScheduledTaskOut,
)
async def legacy_update_scheduled_task(
    cid: Annotated[str, Path(description="Container the ad-hoc prompt/schedule is bound to.")],
    sid: Annotated[str, Path(description="Scheduled-task id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> Response:
    """Deprecated: update a schedule from the old container-scoped body.

    Legacy container-scoped route (Task 20). Requires a tenant-scoped bearer
    token; staff principals (``tenant_id`` is None) get 403 `forbidden`. Returns
    404 `not_found` if the schedule is not found for the tenant. If ``task_body``
    is present, a new ad-hoc prompt is created (bound to ``cid``) and the target
    is rewired; otherwise name/schedule/timezone/enabled updates are delegated
    to the shared update helper (400 `validation_error` on a bad schedule).
    Returns the updated schedule (HTTP 200) with `Deprecation`/`Sunset` headers.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "scheduled tasks are tenant-scoped")

    payload = await request.json()
    task_body: dict[str, Any] | None = payload.get("task_body")

    async with request.app.state.session_factory() as session:
        existing = await _load_owned_schedule(session, principal.tenant_id, sid)

        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}

        if "name" in payload:
            values["name"] = payload["name"]

        if task_body is not None:
            prompt_text: str = task_body.get("prompt", "")
            adhoc_name: str = payload.get("name") or existing["name"]
            pid = await _create_adhoc_prompt(
                session, principal.tenant_id, adhoc_name, prompt_text, principal.user_id
            )
            target = validate_target(
                {"kind": "prompt", "container_id": cid, "prompt_id": pid, "variables": {}}
            )
            await _assert_target_exists(session, principal.tenant_id, target)
            values["target"] = target

        if "enabled" in payload:
            values["enabled"] = payload["enabled"]

        schedule = payload.get("schedule") if "schedule" in payload else existing["schedule"]
        timezone = payload.get("timezone") if "timezone" in payload else existing["timezone"]
        run_at: str | None = payload.get("run_at")

        recompute = (
            "schedule" in payload
            or "timezone" in payload
            or run_at is not None
            or (payload.get("enabled") is True and not existing["enabled"])
        )
        if "schedule" in payload:
            values["schedule"] = schedule
        if "timezone" in payload:
            values["timezone"] = timezone

        result = await _do_update_scheduled_task(
            session,
            tenant_id=principal.tenant_id,
            sid=sid,
            existing=existing,
            values=values,
            schedule=schedule,
            timezone=timezone,
            run_at=run_at,
            recompute=recompute,
        )

    resp = JSONResponse(result)
    _legacy_headers(resp)
    return resp
