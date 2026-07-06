from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from agentcore.models import (
    AgentConfig,
    GitPushConfig,
    OutputContract,
    ResolvedLimits,
    ShimMcpServer,
    ShimSkill,
    ShimTaskRequest,
    TaskBody,
    TaskLimits,
)
from control_plane import lifecycle
from control_plane.auth import Principal
from control_plane.auth.crypto import decrypt_secret, load_key_from_env
from control_plane.config import Settings
from control_plane.credentials_service import (
    decrypt_row,
    provider_for_model,
    provider_is_keyless,
)
from control_plane.errors import (
    APIError,
    api_error,
    not_found,
    session_busy,
    session_driver_mismatch,
    too_many_tasks,
)
from control_plane.ids import new_task_id
from control_plane.limits import LimitExceeded, resolve_limits
from control_plane.model_catalog import driver_can_use_subscription
from control_plane.models_db import containers, events, git_remotes, tasks
from control_plane.models_db import mcp_servers as mcp_servers_table
from control_plane.models_db import prompts
from control_plane.models_db import skills as skills_table
from control_plane.prompts_service import resolve_body
from control_plane.routers.containers import (
    _load_owned_container,
    _principal,
    _session,
    _tid,
    load_tenant_limits,
)
from control_plane.mcp_service import resolve_mcp_for_request
from control_plane.schemas import SessionOut, TaskOut, TaskSubmitResponse
from control_plane.shim_client import ShimClient, ShimError, ShimTooManyTasks
from control_plane.skills_service import resolve_skills_for_request
from control_plane.sse import format_sse, parse_event_line, should_forward

router = APIRouter()

# Drivers that shell out to a native CLI which discovers SKILL.md / MCP config
# on disk (as opposed to the in-process "vanilla" driver). Skills and MCP
# servers are only resolved for these.
SHELL_OUT_DRIVERS = ("opencode", "codex", "claude-code")


async def _load_tenant_rows_by_id(
    session: AsyncSession, table: Any, tenant_id: str, ids: list[str]
) -> list[dict[str, Any]]:
    """Load rows from ``table`` scoped to ``tenant_id`` whose id is in ``ids``."""
    return [
        dict(r)
        for r in (
            await session.execute(
                sa.select(table).where(
                    table.c.tenant_id == tenant_id,
                    table.c.id.in_(ids),
                )
            )
        ).mappings().all()
    ]


class PromptTaskBody(BaseModel):
    """Submit-by-prompt body: like TaskBody but the prompt comes from a stored
    prompt id, with caller-supplied variable values."""
    prompt_id: str
    variables: dict[str, str] = Field(default_factory=dict)
    output: OutputContract = Field(default_factory=OutputContract)
    limits: TaskLimits = Field(default_factory=TaskLimits)
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


async def _load_prompt(session: AsyncSession, tenant_id: str, pid: str) -> dict[str, Any]:
    """Load a prompt's body + variables scoped to the tenant, or 404."""
    row = (
        await session.execute(
            select(prompts.c.body, prompts.c.variables).where(
                prompts.c.id == pid,
                prompts.c.tenant_id == tenant_id,
            )
        )
    ).mappings().first()
    if row is None:
        raise api_error(404, "prompt_not_found", "prompt not found", "prompt_id")
    return dict(row)


# ---------------------------------------------------------------------------
# Pure builders (Unit 3 Task 16) — importable for unit tests.
# The credential lives ONLY in build_shim_request's output; it is NEVER
# passed into build_task_row or written to any DB column.
# ---------------------------------------------------------------------------


def build_task_row(
    *,
    task_id: str,
    tenant_id: str,
    container_id: str,
    task: TaskBody,
    config: AgentConfig,
    scheduled_task_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """The persisted tasks row.  ``body`` is the task object ONLY (no
    credential); ``config_snapshot`` is the container config at submit time
    (spec §4.6, §8.5)."""
    return {
        "id": task_id,
        "tenant_id": tenant_id,
        "container_id": container_id,
        "scheduled_task_id": scheduled_task_id,
        "session_id": session_id,
        "driver": config.driver,
        "model": config.model,
        "body": task.model_dump(mode="json"),
        "config_snapshot": config.model_dump(mode="json"),
        "status": "pending",
    }


def build_task_skills(
    config: AgentConfig, skill_rows: list[dict[str, Any]]
) -> list[ShimSkill]:
    """Resolve the container's selected skills — for the shell-out drivers that
    natively discover SKILL.md (opencode, codex). Other drivers get nothing."""
    if config.driver not in SHELL_OUT_DRIVERS or not config.skills:
        return []
    return resolve_skills_for_request(config.skills, skill_rows)


def build_task_mcp_servers(
    config: AgentConfig, rows: list[dict[str, Any]], master_key: bytes
) -> list[ShimMcpServer]:
    """Resolve the container's selected MCP servers for the shell-out drivers
    (opencode, codex). Other drivers get nothing — mirrors build_task_skills."""
    if config.driver not in SHELL_OUT_DRIVERS or not config.mcp_servers:
        return []
    return resolve_mcp_for_request(config.mcp_servers, rows, master_key)


def build_shim_request(
    *,
    task_id: str,
    task: TaskBody,
    config: AgentConfig,
    limits: ResolvedLimits,
    credential: str,
    credential_kind: str = "api_key",
    credential_meta: dict | None = None,  # type: ignore[type-arg]
    git_push: GitPushConfig | None = None,
    git_snapshots: bool = True,
    skills: list[ShimSkill] | None = None,
    mcp_servers: list[ShimMcpServer] | None = None,
    session_id: str | None = None,
    session_is_continuation: bool = False,
) -> ShimTaskRequest:
    """In-memory request to the shim.  The credential (and git token) live here
    only — never part of build_task_row's output."""
    return ShimTaskRequest(
        task_id=task_id,
        task=task,
        config=config,
        limits=limits,
        llm_credential=credential,
        credential_kind=credential_kind,
        credential_meta=credential_meta or {},
        git_push=git_push,
        git_snapshots=git_snapshots,
        skills=skills or [],
        mcp_servers=mcp_servers or [],
        session_id=session_id,
        session_is_continuation=session_is_continuation,
    )


def build_git_push(
    remote_row: dict[str, Any] | None, master_key: bytes
) -> GitPushConfig | None:
    """The per-task auto-push block (workspace git rollback spec).

    SSH private key decrypted in memory only — same handling rules as llm_credential."""
    if (
        not remote_row
        or not remote_row.get("enabled")
        or not remote_row.get("ssh_private_key_ciphertext")
    ):
        return None
    return GitPushConfig(
        url=remote_row["url"],
        ssh_private_key=decrypt_secret(remote_row["ssh_private_key_ciphertext"], master_key),
        branch=remote_row["branch"],
    )


def resolve_git_push(
    remote_row: dict[str, Any] | None, key_loader: Callable[[], bytes]
) -> GitPushConfig | None:
    """build_git_push, guarded for the submit path: the master key is loaded
    only when an enabled remote with a stored SSH key exists, and any git-side
    problem (missing CREDENTIAL_ENCRYPTION_KEY, corrupt ciphertext) degrades to
    "no auto-push" — a task submission must never fail because of git."""
    if (
        not remote_row
        or not remote_row.get("enabled")
        or not remote_row.get("ssh_private_key_ciphertext")
    ):
        return None
    try:
        return build_git_push(remote_row, key_loader())
    except Exception:  # noqa: BLE001 — degrade to no auto-push
        return None


def git_event_remote_values(payload: dict[str, Any]) -> dict[str, Any] | None:
    """git_remotes updates for a shim 'git' event; None if not a push event."""
    if payload.get("op") != "push":
        return None
    ok = bool(payload.get("ok"))
    return {
        "last_push_status": "pushed" if ok else "failed",
        "last_push_error": None if ok else payload.get("error", "push_failed"),
        "last_push_at": datetime.now(UTC),
    }


def pick_provider_credential(
    rows: list[dict],  # type: ignore[type-arg]
    *,
    kill_switch: bool,
    subscription_usable: bool = True,
) -> str | None:
    """Choose the auth_method to use for a provider: oauth_subscription → api_key.

    Returns the chosen ``auth_method`` string, or None if nothing is usable.
    The oauth row is chosen whenever it is active and not kill-switched, EVEN IF
    its stored access token is stale — ``ensure_fresh_oauth`` refreshes it at
    submit time. The long-task rule (the token must outlast the task timeout,
    spec §6.5) is enforced on the FRESH token after refresh, in the submit path,
    not here — checking the possibly-stale stored token would reject a
    perfectly refreshable credential.

    ``subscription_usable`` is False when the selected driver cannot consume this
    provider's subscription (e.g. opencode/vanilla with an anthropic subscription,
    which has no working backend in those drivers — see driver_can_use_subscription).
    In that case the oauth row is skipped so we fall back to an API key or report
    no usable credential, rather than handing the driver a token it will reject.
    """
    oauth = next((r for r in rows if r["auth_method"] == "oauth_subscription"), None)
    api_key = next((r for r in rows if r["auth_method"] == "api_key"), None)
    if (
        subscription_usable
        and oauth is not None
        and not kill_switch
        and oauth.get("status") == "active"
    ):
        return "oauth_subscription"
    if api_key is not None:
        return "api_key"
    return None


async def forward_to_shim(
    settings: Settings,
    row: Any,
    shim_req: ShimTaskRequest,
    session: Any,
    task_id: str,
) -> dict:  # type: ignore[type-arg]
    """Submit shim_req to the container's shim and return the ack dict.

    Extracted as a named module-level coroutine so tests can monkeypatch it.
    Handles ShimTooManyTasks (delete row, raise 429) and ShimError (mark failed, raise 502).
    """
    try:
        async with _shim_for(settings, row) as shim:
            return dict(await shim.submit_task(shim_req))
    except ShimTooManyTasks:
        await session.execute(tasks.delete().where(tasks.c.id == task_id))
        await session.commit()
        raise too_many_tasks() from None
    except ShimError as exc:
        await session.execute(
            tasks.update().where(tasks.c.id == task_id).values(
                status="failed", error_code="shim_unavailable", error_message=str(exc),
            )
        )
        await session.commit()
        raise APIError(502, "shim_unavailable", "shim is unavailable") from exc


def _shim_for(settings: Settings, row: Any) -> ShimClient:
    # If the container was provisioned with host port binding (e.g. on macOS
    # where container IPs are not routable), use the stored host URL directly.
    resources: dict[str, Any] = row.resources or {}
    host_shim_url = resources.get("_host_shim_url")
    base_url = host_shim_url or f"http://{row.docker_name}:{settings.shim_port}"
    return ShimClient(base_url=base_url, token=row.shim_token)


def _row_to_task_out(row: Any, container_name: str | None = None) -> TaskOut:
    body = row.body or {}
    error = None
    if row.error_code:
        error = {"code": row.error_code, "message": row.error_message or row.error_code}
    return TaskOut(
        task_id=row.id,
        container_id=row.container_id,
        container_name=container_name,
        session_id=row.session_id,
        prompt=body.get("prompt", ""),
        status=row.status,
        driver=row.driver,
        model=row.model,
        config_snapshot=AgentConfig(**row.config_snapshot),
        result=row.result,
        error=error,
        iterations_used=row.iterations_used,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        started_at=row.started_at.isoformat() if row.started_at else None,
        ended_at=row.ended_at.isoformat() if row.ended_at else None,
        created_at=row.created_at.isoformat(),
    )


async def _session_precheck(
    session: AsyncSession, *, tenant_id: str, cid: str, session_id: str, driver: str,
) -> bool:
    """Validate `session_id` against prior tasks in this container/tenant.

    Returns True if this is a continuation (a prior task already used this
    session_id), False if this is the first task in a new session. Raises
    409 session_driver_mismatch / session_busy (driver-sessions spec §5).
    """
    locked_driver = (
        await session.execute(
            sa.select(tasks.c.driver)
            .where(
                tasks.c.session_id == session_id,
                tasks.c.container_id == cid,
                tasks.c.tenant_id == tenant_id,
            )
            .order_by(tasks.c.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if locked_driver is None:
        return False
    if locked_driver != driver:
        raise session_driver_mismatch(
            f"session {session_id!r} was created with driver {locked_driver!r}; "
            f"this container's current driver is {driver!r}"
        )
    busy: int = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(tasks)
            .where(
                tasks.c.session_id == session_id,
                tasks.c.container_id == cid,
                tasks.c.status.in_(("pending", "running")),
            )
        )
    ).scalar_one()
    if busy > 0:
        raise session_busy(f"session {session_id!r} already has a task in flight")
    return True


async def submit_task_core(
    session: AsyncSession,
    *,
    settings: Settings,
    session_factory: Any,
    docker_client: Any,
    shim_dispatcher: Any,
    tenant_id: str,
    cid: str,
    body: TaskBody,
    scheduled_task_id: str | None = None,
) -> dict:  # type: ignore[type-arg]
    """Submit a task to a container — shared by the HTTP endpoint and the
    scheduler sweep. Brings the container to running, resolves limits and
    credentials, persists the row, forwards to the shim, and spawns event
    ingestion. The credential is decrypted in memory only, never persisted."""
    row = await _load_owned_container(session, tenant_id, cid)
    tenant_limits = await load_tenant_limits(session, tenant_id)

    # Bring the container to running under admission control (spec §4.6 step 2).
    limit = int(tenant_limits.get("max_running_containers", 5))
    await lifecycle.bring_to_running(
        session, docker_client, shim_dispatcher, cid, tenant_id, limit=limit, settings=settings
    )
    await session.commit()

    row = await _load_owned_container(session, tenant_id, cid)
    config = AgentConfig(**row.config)

    session_is_continuation = False
    if body.session_id is not None:
        session_is_continuation = await _session_precheck(
            session, tenant_id=tenant_id, cid=cid,
            session_id=body.session_id, driver=config.driver,
        )

    if not body.prompt.strip():
        raise APIError(400, "validation_error", "prompt is required", "prompt")
    if len(body.prompt.encode("utf-8")) > 100 * 1024:
        raise APIError(400, "validation_error", "prompt exceeds 100 KiB", "prompt")

    try:
        resolved = resolve_limits(body.limits, tenant_limits, config)
    except LimitExceeded as exc:
        raise api_error(400, "validation_error", exc.message, exc.field) from exc

    inflight: int = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(tasks)
            .where(
                tasks.c.container_id == cid,
                tasks.c.status.in_(("pending", "running")),
            )
        )
    ).scalar_one()
    if inflight >= tenant_limits.get("max_concurrent_tasks_per_container", 4):
        raise too_many_tasks()

    # Credential lookup + decrypt (spec §4.5). Never persisted.
    provider = provider_for_model(config.model)
    credential = ""
    credential_kind = "api_key"
    credential_meta: dict[str, Any] = {}
    credential_used = "keyless"
    if not provider_is_keyless(provider):
        master = load_key_from_env()
        now = datetime.now(UTC)
        cred_rows = [
            dict(r)
            for r in (
                await session.execute(
                    sa.select(t.credentials).where(
                        t.credentials.c.tenant_id == tenant_id,
                        t.credentials.c.provider == provider,
                    )
                )
            ).mappings().all()
        ]
        chosen = pick_provider_credential(
            cred_rows,
            kill_switch=settings.oauth_subscription_kill_switch,
            subscription_usable=driver_can_use_subscription(config.driver, provider),
        )
        if chosen == "oauth_subscription":
            from control_plane.oauth_service import OAuthReauthRequired, ensure_fresh_oauth

            oauth_row = next(
                r for r in cred_rows if r["auth_method"] == "oauth_subscription"
            )
            has_api_key = any(r["auth_method"] == "api_key" for r in cred_rows)
            try:
                fresh = await ensure_fresh_oauth(
                    session, oauth_row, settings=settings, master_key=master, now=now
                )
                await session.commit()
            except OAuthReauthRequired:
                await session.commit()
                chosen = "api_key" if has_api_key else None
            else:
                # Long-task rule (spec §6.5): enforce on the FRESH token — it must
                # outlast the task timeout, else fall back rather than risk it
                # expiring mid-task.
                if (fresh["expires_at"] - now).total_seconds() < resolved.timeout_seconds:
                    chosen = "api_key" if has_api_key else None
                else:
                    credential = fresh["access_token"]
                    credential_kind = "oauth_subscription"
                    credential_meta = {
                        "account_id": fresh["account_id"],
                        "expires_ms": int(fresh["expires_at"].timestamp() * 1000),
                        "refresh_token": fresh["refresh_token"],
                        "id_token": fresh.get("id_token"),
                    }
                    credential_used = "oauth_subscription"
        if chosen == "api_key":
            api_row = next(r for r in cred_rows if r["auth_method"] == "api_key")
            credential = decrypt_row(api_row, master)
            credential_kind = "api_key"
            credential_used = "api_key"
        elif chosen is None:
            raise api_error(
                400, "no_credential",
                f"No usable {provider} credential for this tenant",
            )

    task_id = new_task_id()
    task_row = build_task_row(
        task_id=task_id, tenant_id=tenant_id, container_id=cid, task=body,
        config=config, scheduled_task_id=scheduled_task_id, session_id=body.session_id,
    )
    await session.execute(tasks.insert().values(**task_row))
    await session.commit()

    # Linked (pull-mode) containers never snapshot/push: the workspace is a
    # clone of the upstream repo, so the shim must not commit or push back up.
    linked = row.git_mode == "linked"
    remote_row = (
        await session.execute(
            sa.select(git_remotes).where(git_remotes.c.container_id == cid)
        )
    ).mappings().first()
    git_push = None if linked else resolve_git_push(
        dict(remote_row) if remote_row is not None else None, load_key_from_env
    )

    task_skills: list[ShimSkill] = []
    if config.driver in SHELL_OUT_DRIVERS and config.skills:
        skill_rows = await _load_tenant_rows_by_id(
            session, skills_table, tenant_id, config.skills
        )
        task_skills = build_task_skills(config, skill_rows)

    task_mcp: list[ShimMcpServer] = []
    if config.driver in SHELL_OUT_DRIVERS and config.mcp_servers:
        mcp_rows = await _load_tenant_rows_by_id(
            session, mcp_servers_table, tenant_id, config.mcp_servers
        )
        task_mcp = build_task_mcp_servers(config, mcp_rows, load_key_from_env())

    shim_req = build_shim_request(
        task_id=task_id, task=body, config=config, limits=resolved,
        credential=credential, credential_kind=credential_kind,
        credential_meta=credential_meta, git_push=git_push,
        git_snapshots=not linked,
        skills=task_skills,
        mcp_servers=task_mcp,
        session_id=body.session_id,
        session_is_continuation=session_is_continuation,
    )
    ack = await forward_to_shim(settings, row, shim_req, session, task_id)

    started_at = datetime.now(UTC)
    await session.execute(
        tasks.update().where(tasks.c.id == task_id).values(
            status="running", started_at=started_at,
        )
    )
    await session.execute(
        containers.update().where(containers.c.id == cid).values(last_task_at=started_at)
    )
    await session.commit()

    asyncio.create_task(
        _ingest_events_to_db(session_factory, _shim_for(settings, row), task_id)
    )

    return TaskSubmitResponse(
        task_id=task_id,
        status=ack.get("status", "running"),
        started_at=ack.get("started_at", started_at.isoformat()),
        credential_used=credential_used,
        session_id=body.session_id,
    ).model_dump()


@router.post("/containers/{cid}/tasks", status_code=200)
async def submit_task(
    cid: str,
    body: TaskBody,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    st = request.app.state
    return await submit_task_core(
        session,
        settings=st.settings,
        session_factory=st.session_factory,
        docker_client=getattr(st, "docker_client", None),
        shim_dispatcher=getattr(st, "shim", None),
        tenant_id=_tid(principal),
        cid=cid,
        body=body,
    )


@router.post("/containers/{cid}/tasks/from-prompt", status_code=200)
async def submit_task_from_prompt(
    cid: str,
    body: PromptTaskBody,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tenant_id = _tid(principal)
    prompt = await _load_prompt(session, tenant_id, body.prompt_id)
    text = resolve_body(prompt["body"], body.variables, prompt.get("variables"))
    st = request.app.state
    return await submit_task_core(
        session,
        settings=st.settings,
        session_factory=st.session_factory,
        docker_client=getattr(st, "docker_client", None),
        shim_dispatcher=getattr(st, "shim", None),
        tenant_id=tenant_id,
        cid=cid,
        body=TaskBody(
            prompt=text,
            output=body.output,
            limits=body.limits,
            metadata={**body.metadata, "prompt_id": body.prompt_id},
            session_id=body.session_id,
        ),
    )


@router.get("/containers/{cid}/tasks")
async def list_tasks(
    cid: str,
    request: Request,
    scheduled_task_id: str | None = None,
    session_id: str | None = None,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tid = _tid(principal)
    await _load_owned_container(session, tid, cid)
    stmt = (
        select(tasks)
        .where(tasks.c.container_id == cid, tasks.c.tenant_id == tid)
        .order_by(tasks.c.created_at.desc())
        .limit(100)
    )
    if scheduled_task_id is not None:
        stmt = stmt.where(tasks.c.scheduled_task_id == scheduled_task_id)
    if session_id is not None:
        stmt = stmt.where(tasks.c.session_id == session_id)
    rows = (await session.execute(stmt)).all()
    return {"tasks": [_row_to_task_out(r).model_dump() for r in rows]}


@router.get("/containers/{cid}/sessions")
async def list_sessions(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tid = _tid(principal)
    await _load_owned_container(session, tid, cid)
    rows = (
        await session.execute(
            sa.select(
                tasks.c.session_id,
                sa.func.min(tasks.c.driver).label("driver"),
                sa.func.count().label("task_count"),
                sa.func.min(tasks.c.created_at).label("first_created_at"),
                sa.func.max(tasks.c.created_at).label("last_created_at"),
                sa.func.bool_or(tasks.c.status.in_(("pending", "running"))).label("busy"),
            )
            .where(tasks.c.container_id == cid, tasks.c.tenant_id == tid, tasks.c.session_id.isnot(None))
            .group_by(tasks.c.session_id)
            .order_by(sa.func.max(tasks.c.created_at).desc())
        )
    ).all()
    return {
        "sessions": [
            SessionOut(
                session_id=r.session_id,
                driver=r.driver,
                task_count=r.task_count,
                first_created_at=r.first_created_at.isoformat(),
                last_created_at=r.last_created_at.isoformat(),
                busy=bool(r.busy),
            ).model_dump()
            for r in rows
        ]
    }


async def recent_tenant_tasks(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int,
) -> list[TaskOut]:
    """Newest tasks across all of a tenant's containers, with container names."""
    rows = (
        await session.execute(
            select(tasks, containers.c.name.label("container_name"))
            .join(containers, containers.c.id == tasks.c.container_id)
            .where(tasks.c.tenant_id == tenant_id)
            .order_by(tasks.c.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_row_to_task_out(r, container_name=r.container_name) for r in rows]


@router.get("/tasks")
async def list_tenant_tasks(
    request: Request,
    limit: int = 50,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tid = _tid(principal)
    limit = max(1, min(limit, 100))
    out = await recent_tenant_tasks(session, tenant_id=tid, limit=limit)
    return {"tasks": [t.model_dump() for t in out]}


async def _load_owned_task(
    session: AsyncSession, tenant_id: str, cid: str, tid: str
) -> Any:
    row = (
        await session.execute(
            select(tasks).where(
                tasks.c.id == tid,
                tasks.c.container_id == cid,
                tasks.c.tenant_id == tenant_id,
            )
        )
    ).first()
    if row is None:
        raise not_found(f"task {tid} not found")
    return row


@router.get("/containers/{cid}/tasks/{tid}")
async def get_task(
    cid: str,
    tid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tenant_id = _tid(principal)
    await _load_owned_container(session, tenant_id, cid)
    row = await _load_owned_task(session, tenant_id, cid, tid)
    return _row_to_task_out(row).model_dump()


@router.post("/containers/{cid}/tasks/{tid}/cancel")
async def cancel_task(
    cid: str,
    tid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tenant_id = _tid(principal)
    crow = await _load_owned_container(session, tenant_id, cid)
    await _load_owned_task(session, tenant_id, cid, tid)
    async with _shim_for(request.app.state.settings, crow) as shim:
        result = await shim.cancel_task(tid)
    return result


@router.get("/containers/{cid}/tasks/{tid}/events", response_model=None)
async def stream_events(
    cid: str,
    tid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
    after_seq: int | None = None,
) -> StreamingResponse | dict:  # type: ignore[type-arg]
    tenant_id = _tid(principal)
    crow = await _load_owned_container(session, tenant_id, cid)
    await _load_owned_task(session, tenant_id, cid, tid)
    factory = request.app.state.session_factory

    accept = request.headers.get("accept", "")
    if "text/event-stream" not in accept:
        rows = (
            await session.execute(
                select(events)
                .where(events.c.task_id == tid)
                .order_by(events.c.seq.asc())
            )
        ).all()
        return {"events": [
            {"seq": r.seq, "type": r.type, "ts": r.ts.isoformat(), "payload": r.payload}
            for r in rows
            if should_forward(seq=int(r.seq), after_seq=after_seq)
        ]}

    # INCIDENT FIX (sse-db-pool-exhaustion): release the request-scoped pooled
    # connection before streaming.  For a StreamingResponse the Depends(_session)
    # yield-context would otherwise stay open for the WHOLE stream lifetime,
    # pinning one of the pooled connections per open viewer and starving /healthz.
    # Per-event persistence below uses its own short-lived factory() session, so
    # the stream needs no request-scoped connection.  close() is idempotent so
    # the later _session yield-exit (calling close() again) is harmless.
    await session.close()

    async def gen() -> Any:
        shim = _shim_for(request.app.state.settings, crow)
        try:
            async for raw in shim.stream_events(tid, after_seq):
                line = raw.decode("utf-8")
                event = parse_event_line(line)
                if event is None:
                    continue
                if not should_forward(seq=int(event["seq"]), after_seq=after_seq):
                    continue
                # Persist best-effort/async in its own session (does not block forwarding).
                await _persist_event_best_effort(factory, tid, event)
                yield format_sse(line[len("data:"):].strip())
        finally:
            await shim.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _persist_event_best_effort(
    factory: Any, task_id: str, event: dict[str, Any]
) -> None:
    try:
        async with factory() as s:
            stmt = pg_insert(events).values(
                task_id=task_id,
                seq=int(event["seq"]),
                type=event["type"],
                payload=event.get("payload", {}),
            ).on_conflict_do_nothing(index_elements=["task_id", "seq"])
            await s.execute(stmt)
            await _apply_event_to_task_row(s, task_id, event)
            await s.commit()
    except Exception:
        # Best-effort: never break the live stream because persistence failed.
        pass


async def _ingest_events_to_db(
    factory: Any, shim: ShimClient, task_id: str
) -> None:
    """Background event ingestion. This is what makes task history complete even
    when no browser is attached to the SSE route."""
    try:
        async for raw in shim.stream_events(task_id, after_seq=0):
            line = raw.decode("utf-8")
            event = parse_event_line(line)
            if event is not None:
                await _persist_event_best_effort(factory, task_id, event)
    finally:
        await shim.aclose()


async def _apply_event_to_task_row(
    session: AsyncSession, task_id: str, event: dict[str, Any]
) -> None:
    payload = event.get("payload", {})
    if event.get("type") == "token_update":
        await session.execute(
            tasks.update().where(tasks.c.id == task_id).values(
                tokens_in=int(payload.get("tokens_in", 0)),
                tokens_out=int(payload.get("tokens_out", 0)),
            )
        )
    if event.get("type") == "status_change":
        to_status = payload.get("to")
        values: dict[str, Any] = {
            "status": to_status,
            "ended_at": datetime.now(UTC),
            "result": payload.get("result"),
        }
        err = payload.get("error") or {}
        if err:
            values["error_code"] = err.get("code")
            values["error_message"] = err.get("message")
        await session.execute(tasks.update().where(tasks.c.id == task_id).values(**values))
    if event.get("type") == "git":
        values = git_event_remote_values(payload)
        if values is not None:
            await session.execute(
                git_remotes.update()
                .where(
                    git_remotes.c.container_id.in_(
                        sa.select(tasks.c.container_id).where(tasks.c.id == task_id)
                    )
                )
                .values(**values)
            )
