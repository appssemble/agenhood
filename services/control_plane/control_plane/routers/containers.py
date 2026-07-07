from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Trigger driver + tool registration so DRIVERS/TOOLS are populated.
import agentcore.drivers.vanilla  # noqa: F401
import agentcore.tools  # noqa: F401
from agentcore.drivers.base import DRIVERS
from agentcore.drivers.vanilla import DEFAULT_SYSTEM_PROMPT, DONE_TOOL, enabled_tool_specs
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from agentcore.prompt import assemble_system_prompt
from agentcore.tools.base import TOOLS
from control_plane import lifecycle
from control_plane.auth import Principal
from control_plane.auth.principal import require_admin, resolve_principal
from control_plane.config import Settings
from control_plane.config_validation import (
    ConfigInvalid,
    validate_config,
    validate_config_against_tenant,
)
from control_plane.docker_ctl.provision import (
    ReadinessFailed,
    destroy_container,
    provision_container,
)
from control_plane.errors import APIError, api_error, not_found, validation_error
from control_plane.ids import new_container_id
from control_plane.mcp_service import filter_known_mcp_server_ids
from control_plane.models_db import containers, templates, tenants
from control_plane.models_db import mcp_servers as mcp_servers_table
from control_plane.models_db import skills as skills_table
from control_plane.resource_limits import resolve_resource_limits
from control_plane.schemas import (
    ConfigOut,
    ConfigPatch,
    ContainerOut,
    CreateContainerRequest,
    ResourceLimitsIn,
)
from control_plane.skills_service import filter_known_skill_ids
from control_plane.tenant_defaults import merge_limits
from control_plane.variants import assert_config_runnable_on_variant


class PauseBody(BaseModel):
    force: bool = False


class UpdateImageRequest(BaseModel):
    image_tag: str


router = APIRouter()

# ---------------------------------------------------------------------------
# Default limits used for the config-preview assembled_prompt. These are
# placeholder values that satisfy assemble_system_prompt's requirement for a
# ResolvedLimits object; they do NOT govern task execution limits.
# ---------------------------------------------------------------------------
_PREVIEW_LIMITS = ResolvedLimits(
    max_iterations=30,
    max_tokens=2_000_000,
    timeout_seconds=1800,
)

# Placeholder TaskBody used for the config preview assembled prompt.
_PREVIEW_TASK = TaskBody(prompt="<preview>")


# ---------------------------------------------------------------------------
# Unit 3 Task 14: container create cap
# ---------------------------------------------------------------------------


class MaxContainersReached(Exception):
    """Tenant has reached its max_containers create cap (spec §4.4)."""


def assert_under_container_cap(*, current_count: int, max_containers: int) -> None:
    """Raise MaxContainersReached if current_count >= max_containers."""
    if current_count >= max_containers:
        raise MaxContainersReached(
            f"tenant at max_containers ({max_containers})"
        )


# ---- dependencies ----------------------------------------------------------
def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


async def _principal(principal: Principal = Depends(resolve_principal)) -> Principal:
    """Require a tenant-scoped principal (tenant_id must be non-None).

    Staff principals (tenant_id=None) cannot operate on tenant resources;
    they use the admin router instead.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "This endpoint requires a tenant-scoped credential")
    return principal


def _tid(principal: Principal) -> str:
    """Narrow principal.tenant_id to str for mypy; _principal guard ensures it's non-None."""
    assert principal.tenant_id is not None  # guaranteed by _principal dep
    return principal.tenant_id


# ---- helpers ---------------------------------------------------------------
async def load_tenant_limits(session: AsyncSession, tenant_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            select(tenants.c.limits).where(tenants.c.id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"tenant {tenant_id} not found")
    # Resolve against current defaults so a tenant that never froze a key (e.g.
    # allowed_drivers) inherits the platform's current value. See persisted_limits.
    return merge_limits(dict(row))


def _preview_prompt(cfg: AgentConfig) -> str:
    """Assemble a system-prompt preview from the config (no task or live limits)."""
    tool_specs = enabled_tool_specs(cfg)
    tool_specs_with_done = tool_specs if DONE_TOOL in tool_specs else [*tool_specs, DONE_TOOL]
    return assemble_system_prompt(
        config=cfg,
        driver_default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        tool_specs=tool_specs_with_done,
        task=_PREVIEW_TASK,
        limits=_PREVIEW_LIMITS,
    )


def _row_to_container_out(row: Any) -> ContainerOut:
    return ContainerOut(
        id=row.id,
        name=row.name,
        external_id=row.external_id,
        metadata=row.metadata,
        status=row.status,
        image_tag=row.image_tag,
        image_variant=row.image_variant,
        template_id=row.template_id,
        config=AgentConfig(**row.config),
        last_task_at=row.last_task_at.isoformat() if row.last_task_at else None,
        created_at=row.created_at.isoformat(),
        error_message=row.error_message,
        git_mode=row.git_mode,
        mem_limit=row.mem_limit,
        cpus=row.cpus,
    )


async def _resolve_create_config(
    session: AsyncSession, req: CreateContainerRequest
) -> tuple[AgentConfig, str | None]:
    """Return the active config and the seed template_id (if any).

    Precedence: an inline ``config`` wins; else the named template's config;
    else the driver default's built-in template.  An inline ``config`` may
    also override a template — here we treat inline as a complete config when
    present.
    """
    template_id: str | None = None
    base: dict[str, Any] | None = None

    if req.template_id is not None:
        trow = (
            await session.execute(
                select(templates).where(templates.c.id == req.template_id)
            )
        ).first()
        if trow is None:
            raise not_found(f"template {req.template_id} not found")
        template_id = trow.id
        base = {
            "driver": trow.driver,
            "model": trow.model,
            "system_prompt": trow.system_prompt,
            "system_prompt_mode": trow.system_prompt_mode,
            "tools": trow.tools,
            "context": trow.context,
            "skills": list(trow.skills or []),
            "mcp_servers": list(trow.mcp_servers or []),
        }

    if req.config is not None:
        # Inline config: it is the complete active config (overrides template).
        cfg: AgentConfig = req.config
    elif base is not None:
        if base["model"] is None:
            raise validation_error(
                "template has no model; provide config.model", field="model"
            )
        cfg = AgentConfig(**base)
    else:
        raise validation_error("provide either template_id or config", field="config")

    return cfg, template_id


async def _load_owned_container(
    session: AsyncSession, tenant_id: str, cid: str
) -> Any:
    row = (
        await session.execute(
            select(containers).where(
                containers.c.id == cid,
                containers.c.tenant_id == tenant_id,
            )
        )
    ).first()
    if row is None:
        raise not_found(f"container {cid} not found")
    return row


# ---- routes ----------------------------------------------------------------
@router.post("/containers", status_code=201)
async def create_container(
    request: Request,
    body: CreateContainerRequest,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    settings: Settings = request.app.state.settings
    tid = _tid(principal)
    limits = await load_tenant_limits(session, tid)

    config, template_id = await _resolve_create_config(session, body)
    # Raises validation_error before any Docker work.
    validate_config(config, limits)

    # Image-variant feature gate (spec §9.1): refuse driver/tool whose
    # requires_image_feature the chosen variant does not provide.
    variant = body.image_variant or "full"
    assert_config_runnable_on_variant(
        variant=variant,
        driver_name=config.driver,
        tool_names=list(config.tools or []),
        drivers=DRIVERS,
        tools=TOOLS,
    )

    mem_limit, cpus = resolve_resource_limits(
        variant=variant,
        requested_mem_limit=body.resource_limits.mem_limit if body.resource_limits else None,
        requested_cpus=body.resource_limits.cpus if body.resource_limits else None,
        settings=settings,
    )

    # Total-provisioned cap (spec §4.4): every row not in 'destroyed'.
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(containers)
            .where(
                containers.c.tenant_id == tid,
                containers.c.status != "destroyed",
            )
        )
    ).scalar_one()
    try:
        assert_under_container_cap(
            current_count=count, max_containers=int(limits["max_containers"])
        )
    except MaxContainersReached as exc:
        raise api_error(
            409, "max_containers_reached", "Tenant has reached its container limit"
        ) from exc

    if body.external_id is not None:
        existing = (
            await session.execute(
                select(containers.c.id).where(
                    containers.c.tenant_id == tid,
                    containers.c.external_id == body.external_id,
                    containers.c.status != "destroyed",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise APIError(
                409,
                "external_id_in_use",
                "external_id already has a live container",
                field="external_id",
            )

    cid = new_container_id()
    image_tag = body.image_tag or settings.agent_image_tag
    max_workers = int(limits.get("max_concurrent_tasks_per_container", 4))
    reuse_volume = body.volume_id

    try:
        result = await provision_container(
            settings=settings,
            container_id=cid,
            tenant_id=tid,
            image_tag=image_tag,
            max_workers=max_workers,
            mem_limit=mem_limit,
            cpus=cpus,
            reuse_volume_name=reuse_volume,
            extra_env=settings.agent_extra_env,
        )
    except ReadinessFailed as exc:
        # No row persisted; partial container+volume already cleaned up (spec §4.7).
        raise APIError(503, "container_not_runnable", "container did not become ready") from exc

    # Merge any host-accessible shim URL into resources so _shim_for can use it
    # on hosts where Docker container names are not resolvable (e.g. macOS).
    resources: dict[str, Any] = dict(body.resources or {})
    if result.host_shim_url:
        resources["_host_shim_url"] = result.host_shim_url

    try:
        await session.execute(
            containers.insert().values(
                id=cid,
                tenant_id=tid,
                name=body.name,
                external_id=body.external_id,
                metadata=body.metadata,
                docker_name=result.docker_name,
                volume_name=result.volume_name,
                shim_token=result.shim_token,
                image_tag=image_tag,
                image_variant=body.image_variant,
                template_id=template_id,
                config=config.model_dump(),
                status="running",
                resources=resources,
                mem_limit=mem_limit,
                cpus=cpus,
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        await destroy_container(
            docker_name=result.docker_name,
            volume_name=result.volume_name,
            delete_volume=(reuse_volume is None),
        )
        raise APIError(
            409,
            "external_id_in_use",
            "external_id already has a live container",
            field="external_id",
        ) from exc

    row = (
        await session.execute(select(containers).where(containers.c.id == cid))
    ).first()
    return _row_to_container_out(row).model_dump()


@router.get("/containers")
async def list_containers(
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
    external_id: str | None = None,
    status: str | None = None,
) -> dict:  # type: ignore[type-arg]
    q = select(containers).where(containers.c.tenant_id == _tid(principal))
    if external_id is not None:
        q = q.where(containers.c.external_id == external_id)
    if status is not None:
        q = q.where(containers.c.status == status)
    rows = (await session.execute(q)).all()
    return {"containers": [_row_to_container_out(r).model_dump() for r in rows]}


@router.get("/containers/{cid}")
async def get_container(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = await _load_owned_container(session, _tid(principal), cid)
    return _row_to_container_out(row).model_dump()


@router.get("/containers/{cid}/config")
async def get_config(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = await _load_owned_container(session, _tid(principal), cid)
    cfg = AgentConfig(**row.config)
    preview = _preview_prompt(cfg)
    return ConfigOut(config=cfg, assembled_prompt=preview).model_dump()


@router.patch("/containers/{cid}/config")
async def patch_config(
    cid: str,
    patch: ConfigPatch,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    # Verify ownership — raises not_found if missing or wrong tenant.
    tid = _tid(principal)
    row = await _load_owned_container(session, tid, cid)
    limits = await load_tenant_limits(session, tid)
    new_config = patch.to_agent_config()
    # Drop skill ids that don't belong to this tenant so a stale/foreign id
    # can't linger in the saved config (spec: opencode skills).
    if new_config.skills:
        owned = [
            dict(r) for r in (
                await session.execute(
                    sa.select(skills_table.c.id).where(
                        skills_table.c.tenant_id == tid,
                        skills_table.c.id.in_(new_config.skills),
                    )
                )
            ).mappings().all()
        ]
        new_config.skills = filter_known_skill_ids(new_config.skills, owned)
    if new_config.mcp_servers:
        owned_mcp = [
            dict(r) for r in (
                await session.execute(
                    sa.select(mcp_servers_table.c.id).where(
                        mcp_servers_table.c.tenant_id == tid,
                        mcp_servers_table.c.id.in_(new_config.mcp_servers),
                    )
                )
            ).mappings().all()
        ]
        new_config.mcp_servers = filter_known_mcp_server_ids(new_config.mcp_servers, owned_mcp)
    # Raises validation_error on bad config; applies to subsequent tasks only.
    validate_config(new_config, limits)
    # Unit 3 Task 15: re-validate against tenant allowed_drivers/models (spec §6.2).
    try:
        validate_config_against_tenant(new_config, limits)
    except ConfigInvalid as exc:
        raise api_error(400, "validation_error", exc.message, exc.field) from exc

    # Image-variant feature gate (spec §9.1): a slim container can never hold a
    # chromium-needing config, even after a PATCH.
    assert_config_runnable_on_variant(
        variant=row.image_variant or "full",
        driver_name=new_config.driver,
        tool_names=list(new_config.tools or []),
        drivers=DRIVERS,
        tools=TOOLS,
    )

    await session.execute(
        containers.update()
        .where(containers.c.id == cid)
        .values(config=new_config.model_dump())
    )
    await session.commit()
    preview = _preview_prompt(new_config)
    return ConfigOut(config=new_config, assembled_prompt=preview).model_dump()


# ---------------------------------------------------------------------------
# Lifecycle routes (spec §4.10/§4.12) — Task 10
# ---------------------------------------------------------------------------


def _docker(request: Request) -> Any:
    """Return the docker client attached to app state (or None in tests)."""
    return getattr(request.app.state, "docker_client", None)


def _shim(request: Request) -> Any:
    """Return the app-level shim attached to app state (or None in tests)."""
    return getattr(request.app.state, "shim", None)


@router.post("/containers/{cid}/destroy", status_code=200)
async def destroy_container_ep(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Destroy a container (spec §4.2): remove the Docker container, keep the
    workspace volume + record so it can be restored. Recoverable."""
    await _load_owned_container(session, _tid(principal), cid)
    await lifecycle.destroy(
        session,
        _docker(request),
        _shim(request),
        cid,
        actor_type="tenant",
        actor_id=_tid(principal),
    )
    await session.commit()
    status = await lifecycle.current_status(session, cid)
    return {"id": cid, "status": status or "archived"}


@router.delete("/containers/{cid}", status_code=200)
async def delete_container_ep(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Permanently delete a container and all data about it (spec §4.2).

    404 if the container row no longer exists.
    """
    await _load_owned_container(session, _tid(principal), cid)
    await lifecycle.delete(
        session,
        _docker(request),
        _shim(request),
        cid,
        actor_type="tenant",
        actor_id=_tid(principal),
    )
    await session.commit()
    return {"id": cid, "status": "deleted"}


@router.post("/containers/{cid}/restore", status_code=200)
async def restore_container_ep(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Restore a destroyed (archived) container back to running (spec §4.2)."""
    tid = _tid(principal)
    await _load_owned_container(session, tid, cid)
    tenant_limits = await load_tenant_limits(session, tid)
    limit = int(tenant_limits.get("max_running_containers", 5))
    await lifecycle.restore(
        session,
        _docker(request),
        _shim(request),
        cid,
        tid,
        limit=limit,
        settings=_settings(request),
        actor_type="tenant",
        actor_id=tid,
    )
    await session.commit()
    return {"id": cid, "status": "running"}


@router.post("/containers/{cid}/pause")
async def pause_container(
    cid: str,
    request: Request,
    body: PauseBody = Body(default_factory=PauseBody),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Pause a running container (spec §4.10).

    Pass ``force=true`` to cancel in-flight tasks first; otherwise a busy
    container returns 409.
    """
    await _load_owned_container(session, _tid(principal), cid)
    docker_client = _docker(request)
    shim_client = _shim(request)
    await lifecycle.pause(
        session,
        docker_client,
        shim_client,
        cid,
        force=body.force,
        actor_type="tenant",
        actor_id=_tid(principal),
    )
    await session.commit()
    return {"id": cid, "status": "paused"}


@router.post("/containers/{cid}/update-image", status_code=200)
async def update_container_image(
    cid: str,
    request: Request,
    body: UpdateImageRequest,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Move a container to a different image tag (spec: update-container-image).

    Pulls the target image first, then (for live containers) destroys + rehydrates
    from the retained volume so it returns on the new image. The workspace volume
    is preserved. Any tag is allowed, including downgrades.
    """
    tag = body.image_tag.strip()
    if not tag:
        raise validation_error("image_tag must not be empty")
    tid = _tid(principal)
    await _load_owned_container(session, tid, cid)
    tenant_limits = await load_tenant_limits(session, tid)
    limit = int(tenant_limits.get("max_running_containers", 5))
    await lifecycle.update_image(
        session,
        _docker(request),
        _shim(request),
        cid,
        tid,
        tag,
        limit=limit,
        settings=_settings(request),
        actor_type="tenant",
        actor_id=tid,
    )
    await session.commit()
    status = await lifecycle.current_status(session, cid)
    return {"id": cid, "status": status, "image_tag": tag}


@router.patch("/containers/{cid}/resources", status_code=200)
async def update_container_resources(
    cid: str,
    request: Request,
    body: ResourceLimitsIn,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Update a container's memory/CPU limits.

    Live-updates a running container with no restart; updates then auto-resumes
    a paused one; persists only (applied next rehydrate) for an archived one.
    """
    if body.mem_limit is None and body.cpus is None:
        raise validation_error("at least one of mem_limit or cpus is required")
    tid = _tid(principal)
    row = await _load_owned_container(session, tid, cid)
    settings = _settings(request)
    # A field omitted from the PATCH body falls back to the container's current
    # stored value, which is then re-validated against the global bounds like any
    # explicit request. This keeps resolve_resource_limits to a single code path,
    # but means a single-field PATCH can be rejected citing the *other*, unchanged
    # field if an operator has since narrowed the global bounds.
    mem_limit, cpus = resolve_resource_limits(
        variant=row.image_variant,
        requested_mem_limit=body.mem_limit if body.mem_limit is not None else row.mem_limit,
        requested_cpus=body.cpus if body.cpus is not None else row.cpus,
        settings=settings,
        field_prefix="",  # this body's fields are top-level, not nested under resource_limits
    )
    status = await lifecycle.update_resources(
        session,
        _docker(request),
        cid,
        mem_limit=mem_limit,
        cpus=cpus,
        settings=settings,
        actor_type="tenant",
        actor_id=tid,
    )
    await session.commit()
    return {
        "id": cid,
        "status": status,
        "mem_limit": mem_limit,
        "cpus": cpus,
        "applied": status != "archived",
    }


@router.post("/containers/{cid}/resume")
async def resume_container(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Resume a paused container (spec §4.10)."""
    row = await _load_owned_container(session, _tid(principal), cid)
    if row.status == "running":
        # Already running — idempotent success.
        return {"id": cid, "status": "running"}
    if row.status != "paused":
        raise APIError(409, "container_not_runnable", f"cannot resume from '{row.status}'")
    docker_client = _docker(request)
    app_settings = _settings(request)
    await lifecycle.resume(session, docker_client, cid, settings=app_settings)
    await session.commit()
    return {"id": cid, "status": "running"}


@router.post("/containers/{cid}/recover")
async def recover_container(
    cid: str,
    request: Request,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Admin-only: recover a container stuck in 'error' (spec §4.12).

    Returns 409 if the container is not in 'error'.
    """
    # require_admin already checked role; now verify tenant ownership.
    # Staff principals (is_staff=True, tenant_id=None) can recover any container;
    # admin-role tenants can only recover their own.
    if principal.tenant_id is not None:
        row = await _load_owned_container(session, principal.tenant_id, cid)
    else:
        # Staff: load without tenant filter.
        row = (
            await session.execute(
                select(containers).where(containers.c.id == cid)
            )
        ).first()
        if row is None:
            raise not_found(f"container {cid} not found")

    if row.status != "error":
        raise APIError(
            409,
            "container_not_runnable",
            f"container is '{row.status}'; recover is only valid from 'error'",
        )

    docker_client = _docker(request)
    shim_client = _shim(request)
    app_settings = _settings(request)
    await lifecycle.recover(
        session,
        docker_client,
        shim_client,
        cid,
        actor_type="tenant" if principal.tenant_id else "staff",
        actor_id=principal.tenant_id or principal.user_id,
        settings=app_settings,
    )
    await session.commit()
    return {"id": cid, "status": "running"}
