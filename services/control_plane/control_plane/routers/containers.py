from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any, NamedTuple

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, Path, Query, Request
from pydantic import BaseModel, Field
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
from control_plane.audit import audit
from control_plane.auth import Principal
from control_plane.auth.crypto import load_key_from_env
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
from control_plane.env_vars import public_env_vars, store_env_vars
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
    EnvVarIn,
    EnvVarOut,
    ResourceLimitsIn,
)
from control_plane.skills_service import filter_known_skill_ids
from control_plane.tenant_defaults import merge_limits
from control_plane.variants import assert_config_runnable_on_variant


class PauseBody(BaseModel):
    force: bool = Field(
        default=False,
        description=(
            "When true, cancel any in-flight tasks before pausing. When false, "
            "a container with active tasks is rejected with 409."
        ),
    )


class UpdateImageRequest(BaseModel):
    image_tag: str = Field(
        description=(
            "Docker image tag to move the container onto. Any tag is accepted, "
            "including downgrades. Must be non-empty."
        ),
    )


class ContainerListOut(BaseModel):
    """Envelope returned by the list-containers endpoint."""

    containers: list[ContainerOut] = Field(
        description="Containers owned by the caller's tenant that match the filters.",
    )


class ContainerStatusOut(BaseModel):
    """Minimal lifecycle-action result: the container id and its new status."""

    id: str = Field(description="Container id the action was applied to.")
    status: str = Field(description="Container lifecycle status after the action.")


class UpdateImageResponse(BaseModel):
    """Result of moving a container to a new image tag."""

    id: str = Field(description="Container id that was updated.")
    status: str = Field(description="Container lifecycle status after the update.")
    image_tag: str = Field(description="Image tag the container now runs on.")


class ResourceUpdateResponse(BaseModel):
    """Result of updating a container's memory/CPU limits."""

    id: str = Field(description="Container id that was updated.")
    status: str = Field(description="Container lifecycle status after the update.")
    mem_limit: str = Field(description="Effective memory limit (Docker size string).")
    cpus: float = Field(description="Effective CPU allowance in fractional cores.")
    applied: bool = Field(
        description=(
            "True if the new limits were applied to a live container; false when "
            "only persisted for a later rehydrate (archived container)."
        ),
    )


class TemplateRuntime(NamedTuple):
    """A template's stored runtime values; Nones fall through at create."""

    image_variant: str | None = None
    mem_limit: str | None = None
    cpus: float | None = None
    env_vars: list | None = None  # stored-shape items, copied verbatim


router = APIRouter(tags=["Containers"])

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
) -> tuple[AgentConfig, str | None, TemplateRuntime]:
    """Return the active config, the seed template_id (if any), and its runtime.

    Precedence: an inline ``config`` wins; else the named template's config;
    else the driver default's built-in template.  An inline ``config`` may
    also override a template — here we treat inline as a complete config when
    present.
    """
    template_id: str | None = None
    base: dict[str, Any] | None = None
    tpl_runtime = TemplateRuntime()

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
            "effort": trow.effort,
            "system_prompt": trow.system_prompt,
            "system_prompt_mode": trow.system_prompt_mode,
            "tools": trow.tools,
            "context": trow.context,
            "skills": list(trow.skills or []),
            "mcp_servers": list(trow.mcp_servers or []),
        }
        tpl_runtime = TemplateRuntime(
            image_variant=trow.image_variant,
            mem_limit=trow.mem_limit,
            cpus=trow.cpus,
            env_vars=trow.env_vars,
        )

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

    return cfg, template_id, tpl_runtime


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
@router.post(
    "/containers",
    status_code=201,
    response_model=ContainerOut,
    response_description="The newly provisioned container.",
)
async def create_container(
    request: Request,
    body: CreateContainerRequest,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Provision a new agent container for the caller's tenant.

    Requires a tenant-scoped credential. The active config is resolved from an
    inline ``config`` (which wins), otherwise the named ``template_id``, otherwise
    the driver default. The config is validated against tenant limits and the
    chosen image variant before any Docker work, then a container and workspace
    volume are provisioned and a row is persisted with status ``running``.

    Errors: 400 (validation_error) for an invalid/empty config or a template that
    lacks a model; 404 (not_found) if ``template_id`` does not exist; 409
    (max_containers_reached) if the tenant is at its container cap; 409
    (external_id_in_use) if a live container already uses the given
    ``external_id``; 503 (container_not_runnable) if the container fails to become
    ready (no row is persisted and any partial container/volume is cleaned up).
    """
    settings: Settings = request.app.state.settings
    tid = _tid(principal)
    limits = await load_tenant_limits(session, tid)

    config, template_id, tpl_runtime = await _resolve_create_config(session, body)
    # Raises validation_error before any Docker work.
    validate_config(config, limits)

    # Image-variant feature gate (spec §9.1): refuse driver/tool whose
    # requires_image_feature the chosen variant does not provide.
    variant = body.image_variant or tpl_runtime.image_variant or "full"
    assert_config_runnable_on_variant(
        variant=variant,
        driver_name=config.driver,
        tool_names=list(config.tools or []),
        drivers=DRIVERS,
        tools=TOOLS,
    )

    req_mem = body.resource_limits.mem_limit if body.resource_limits else None
    req_cpus = body.resource_limits.cpus if body.resource_limits else None
    mem_limit, cpus = resolve_resource_limits(
        variant=variant,
        requested_mem_limit=req_mem if req_mem is not None else tpl_runtime.mem_limit,
        requested_cpus=req_cpus if req_cpus is not None else tpl_runtime.cpus,
        settings=settings,
    )

    # Env vars: inline wins outright; else the template's stored list is copied
    # verbatim (ciphertext included — same platform key). Inline secrets must
    # carry a value: at create there is no stored secret to keep.
    if body.env_vars is not None:
        stored_env = store_env_vars(
            [item.model_dump() for item in body.env_vars], None, load_key_from_env
        )
    else:
        stored_env = tpl_runtime.env_vars

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
                image_variant=variant,
                template_id=template_id,
                config=config.model_dump(),
                status="running",
                resources=resources,
                mem_limit=mem_limit,
                cpus=cpus,
                env_vars=stored_env,
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


@router.get(
    "/containers",
    response_model=ContainerListOut,
    response_description="Envelope with the list of matching containers.",
)
async def list_containers(
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
    external_id: Annotated[
        str | None,
        Query(description="Filter to the container carrying this caller-supplied external id."),
    ] = None,
    status: Annotated[
        str | None,
        Query(description="Filter by lifecycle status (e.g. running, paused, archived, error)."),
    ] = None,
) -> dict:  # type: ignore[type-arg]
    """List the caller's containers, optionally filtered.

    Requires a tenant-scoped credential. Only containers owned by the caller's
    tenant are returned. Supply ``external_id`` and/or ``status`` to narrow the
    results.
    """
    q = select(containers).where(containers.c.tenant_id == _tid(principal))
    if external_id is not None:
        q = q.where(containers.c.external_id == external_id)
    if status is not None:
        q = q.where(containers.c.status == status)
    rows = (await session.execute(q)).all()
    return {"containers": [_row_to_container_out(r).model_dump() for r in rows]}


@router.get(
    "/containers/{cid}",
    response_model=ContainerOut,
    response_description="The requested container.",
)
async def get_container(
    cid: Annotated[str, Path(description="Container id to fetch.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Fetch a single container by id.

    Requires a tenant-scoped credential. Returns 404 (not_found) if the container
    does not exist or is not owned by the caller's tenant.
    """
    row = await _load_owned_container(session, _tid(principal), cid)
    return _row_to_container_out(row).model_dump()


@router.get(
    "/containers/{cid}/config",
    response_model=ConfigOut,
    response_description="The container's config plus its assembled system-prompt preview.",
)
async def get_config(
    cid: Annotated[str, Path(description="Container id whose config to fetch.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Return a container's agent config and an assembled system-prompt preview.

    Requires a tenant-scoped credential. The ``assembled_prompt`` is a preview
    rendered with placeholder task/limits and does not reflect live task
    execution. Returns 404 (not_found) if the container is missing or not owned by
    the caller's tenant.
    """
    row = await _load_owned_container(session, _tid(principal), cid)
    cfg = AgentConfig(**row.config)
    preview = _preview_prompt(cfg)
    return ConfigOut(config=cfg, assembled_prompt=preview).model_dump()


@router.patch(
    "/containers/{cid}/config",
    response_model=ConfigOut,
    response_description="The updated config plus its assembled system-prompt preview.",
)
async def patch_config(
    cid: Annotated[str, Path(description="Container id whose config to update.")],
    patch: ConfigPatch,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Update a container's agent config; applies to subsequent tasks only.

    Requires a tenant-scoped credential. Unknown/foreign skill and MCP-server ids
    are silently dropped so only tenant-owned ones persist. The new config is
    validated against tenant limits and the container's image variant.

    Errors: 404 (not_found) if the container is missing or not owned by the
    caller; 400 (validation_error) if the resulting config is invalid or violates
    the tenant's allowed drivers/models or the image variant's feature gate.
    """
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


@router.get(
    "/containers/{cid}/env",
    response_model=list[EnvVarOut],
    response_description="The container's env vars; secret values are masked (null).",
)
async def get_container_env(
    cid: Annotated[str, Path(description="Container id whose env vars to fetch.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> list[dict]:  # type: ignore[type-arg]
    """List a container's environment variables.

    Requires a tenant-scoped credential. Secret values are write-only and
    returned with ``value: null``. Returns 404 (not_found) if the container is
    missing or not owned by the caller's tenant.
    """
    row = await _load_owned_container(session, _tid(principal), cid)
    return public_env_vars(row.env_vars)


@router.put(
    "/containers/{cid}/env",
    response_model=list[EnvVarOut],
    response_description="The saved env vars; secret values are masked (null).",
)
async def put_container_env(
    cid: Annotated[str, Path(description="Container id whose env vars to replace.")],
    body: list[EnvVarIn],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> list[dict]:  # type: ignore[type-arg]
    """Replace a container's environment variables; applies to subsequent tasks.

    Requires a tenant-scoped credential. Full-replace semantics: vars omitted
    from the body are deleted. A secret item with ``value: null`` keeps the
    stored secret; with a value it is (re-)encrypted. Values reach the agent
    process on the next task — like a config change, no restart involved.

    Errors: 400 (validation_error) for bad/reserved/duplicate names, missing
    values, or size/count limits; 404 (not_found) if the container is missing
    or not owned by the caller; 500 (encryption_unavailable) if secrets are
    submitted but the platform has no encryption key configured.
    """
    tid = _tid(principal)
    row = await _load_owned_container(session, tid, cid)
    stored = store_env_vars(
        [item.model_dump() for item in body], row.env_vars, load_key_from_env
    )
    await session.execute(
        containers.update().where(containers.c.id == cid).values(env_vars=stored)
    )
    # Names only — values (secret or not) never reach the audit log.
    await audit(
        session,
        actor_type="tenant",
        actor_id=tid,
        action="container.update_env",
        target_type="container",
        target_id=cid,
        details={
            "names": [i["name"] for i in stored],
            "secret_names": [i["name"] for i in stored if i["secret"]],
        },
    )
    await session.commit()
    return public_env_vars(stored)


# ---------------------------------------------------------------------------
# Lifecycle routes (spec §4.10/§4.12) — Task 10
# ---------------------------------------------------------------------------


def _docker(request: Request) -> Any:
    """Return the docker client attached to app state (or None in tests)."""
    return getattr(request.app.state, "docker_client", None)


def _shim(request: Request) -> Any:
    """Return the app-level shim attached to app state (or None in tests)."""
    return getattr(request.app.state, "shim", None)


@router.post(
    "/containers/{cid}/destroy",
    status_code=200,
    response_model=ContainerStatusOut,
    response_description="The container id and its status after being archived.",
)
async def destroy_container_ep(
    cid: Annotated[str, Path(description="Container id to destroy (archive).")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Destroy (archive) a container, keeping its volume for later restore.

    Requires a tenant-scoped credential. Removes the Docker container but retains
    the workspace volume and the database record so the container can be restored
    (spec §4.2). Recoverable. Returns 404 (not_found) if the container is missing
    or not owned by the caller.
    """
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


@router.delete(
    "/containers/{cid}",
    status_code=200,
    response_model=ContainerStatusOut,
    response_description="The container id and a 'deleted' status.",
)
async def delete_container_ep(
    cid: Annotated[str, Path(description="Container id to permanently delete.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Permanently delete a container and all of its data (irreversible).

    Requires a tenant-scoped credential. Removes the Docker container, workspace
    volume, and database record (spec §4.2); unlike destroy, this cannot be
    restored. Returns 404 (not_found) if the container row no longer exists or is
    not owned by the caller.
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


@router.post(
    "/containers/{cid}/restore",
    status_code=200,
    response_model=ContainerStatusOut,
    response_description="The container id and a 'running' status.",
)
async def restore_container_ep(
    cid: Annotated[str, Path(description="Container id to restore to running.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Restore an archived (or paused) container back to running.

    Requires a tenant-scoped credential. Rehydrates the container from its
    retained volume under admission control, honoring the tenant's
    ``max_running_containers`` limit (spec §4.2). An already-running container is
    an idempotent no-op.

    Errors: 404 (not_found) if the container is missing or not owned by the
    caller; 409 (container_not_runnable) if restored from a terminal state; 503
    (running_capacity_exhausted) if the tenant is at its running-container limit
    and no idle container can be evicted.
    """
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


@router.post(
    "/containers/{cid}/pause",
    response_model=ContainerStatusOut,
    response_description="The container id and a 'paused' status.",
)
async def pause_container(
    cid: Annotated[str, Path(description="Container id to pause.")],
    request: Request,
    body: PauseBody = Body(default_factory=PauseBody),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Pause a running container (spec §4.10).

    Requires a tenant-scoped credential. Pass ``force=true`` to cancel in-flight
    tasks before pausing; otherwise a container with active tasks returns 409
    (container_not_runnable). Returns 404 (not_found) if the container is missing
    or not owned by the caller.
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


@router.post(
    "/containers/{cid}/update-image",
    status_code=200,
    response_model=UpdateImageResponse,
    response_description="The container id, its status, and the new image tag.",
)
async def update_container_image(
    cid: Annotated[str, Path(description="Container id to move to a new image.")],
    request: Request,
    body: UpdateImageRequest,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Move a container to a different image tag (spec: update-container-image).

    Requires a tenant-scoped credential. Pulls the target image first, then (for
    live containers) destroys and rehydrates from the retained volume so it
    returns on the new image. The workspace volume is preserved. Any tag is
    allowed, including downgrades.

    Errors: 400 (validation_error) if ``image_tag`` is empty; 404 (not_found) if
    the container is missing or not owned by the caller; 409
    (container_not_updatable) if the container's state does not allow an update;
    422 (image_unavailable) if the target image cannot be pulled.
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


@router.patch(
    "/containers/{cid}/resources",
    status_code=200,
    response_model=ResourceUpdateResponse,
    response_description=(
        "The container id, status, effective limits, and whether they were applied."
    ),
)
async def update_container_resources(
    cid: Annotated[str, Path(description="Container id whose resource limits to update.")],
    request: Request,
    body: ResourceLimitsIn,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Update a container's memory/CPU limits.

    Requires a tenant-scoped credential. Live-updates a running container with no
    restart; updates then auto-resumes a paused one; persists only (applied on the
    next rehydrate) for an archived one. Omitted fields fall back to the
    container's current stored value, which is then re-validated against the
    global bounds.

    Errors: 400 (validation_error) if neither ``mem_limit`` nor ``cpus`` is given
    or a value is out of bounds; 404 (not_found) if the container is missing or
    not owned by the caller; 409 (container_not_updatable) if the container's
    state does not allow an update; 503 (container_not_runnable) if the Docker
    daemon fails to apply the new limits.
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


@router.post(
    "/containers/{cid}/resume",
    response_model=ContainerStatusOut,
    response_description="The container id and a 'running' status.",
)
async def resume_container(
    cid: Annotated[str, Path(description="Container id to resume.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Resume a paused container (spec §4.10).

    Requires a tenant-scoped credential. An already-running container is an
    idempotent no-op. Returns 404 (not_found) if the container is missing or not
    owned by the caller; 409 (container_not_runnable) if the container is in a
    state other than paused or running.
    """
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


@router.post(
    "/containers/{cid}/recover",
    response_model=ContainerStatusOut,
    response_description="The container id and a 'running' status.",
)
async def recover_container(
    cid: Annotated[str, Path(description="Container id to recover from the 'error' state.")],
    request: Request,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Recover a container stuck in the 'error' state (admin only, spec §4.12).

    Requires the admin role. Staff principals (tenant_id=None) may recover any
    container; admin-role tenants may only recover their own. Recovery is only
    valid from the ``error`` state.

    Errors: 404 (not_found) if the container is missing or not owned by the
    caller; 409 (container_not_runnable) if the container is not in the ``error``
    state.
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
