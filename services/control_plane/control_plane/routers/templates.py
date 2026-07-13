from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select

# Trigger driver + tool registration
import agentcore.drivers.vanilla  # noqa: F401
import agentcore.tools  # noqa: F401
from agentcore.drivers.base import DRIVERS
from agentcore.models import ContextSpec
from agentcore.tools.base import TOOLS
from control_plane.auth.principal import Principal, require_admin, resolve_principal
from control_plane.config import Settings
from control_plane.errors import APIError, api_error, not_found, validation_error
from control_plane.ids import new_template_id
from control_plane.models_db import templates
from control_plane.resource_limits import resolve_resource_limits
from control_plane.variants import assert_config_runnable_on_variant, known_variants

router = APIRouter(tags=["Templates"])


# ---------------------------------------------------------------------------
# Response models (documentation only)
# ---------------------------------------------------------------------------


class TemplateListResponse(BaseModel):
    """Envelope returned by ``GET /templates``."""

    templates: list[dict[str, Any]] = Field(
        description="Built-in templates plus the tenant's own, each enriched "
        "with driver ``capabilities``, ``driver_template`` and "
        "``available_tool_specs`` for the console editor."
    )


# ---------------------------------------------------------------------------
# Pure helpers (testable without DB)
# ---------------------------------------------------------------------------


def normalize_context(raw: Any) -> dict[str, Any]:
    """Parse a submitted context into the full ContextSpec shape.

    Raises pydantic ValidationError on malformed input (e.g. non-string
    variable values) — the write paths map that to a 400 so unusable data is
    rejected at the door instead of failing later at container creation."""
    return ContextSpec.model_validate(raw if raw is not None else {}).model_dump()


def context_view(raw: Any) -> dict[str, Any]:
    """Lenient read-side context normalization.

    Rows written before normalization (built-ins seeded with {}, old clones,
    raw API creates) hold a sparse dict; return the full shape the console
    expects. A malformed legacy row degrades to defaults rather than failing
    the whole request."""
    try:
        return normalize_context(raw)
    except ValidationError:
        return ContextSpec().model_dump()


def context_from_body(raw: Any) -> dict[str, Any]:
    """Normalize a client-submitted context, mapping bad input to a 400."""
    try:
        return normalize_context(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise validation_error(
            f"invalid context: {first['msg']}", field="context"
        ) from exc


def validate_template_runtime(
    *, image_variant: Any, mem_limit: Any, cpus: Any,
    driver: str, tool_names: list[str], settings: Settings,
) -> dict[str, Any]:
    """Validate a template's runtime triple with the same rules container
    create applies. NULLs mean "unset" and skip their check. Returns the
    normalized triple. Raises 400 validation_error (bad value / out of
    bounds) or 409 (slim image with chromium-requiring tools)."""
    if image_variant is not None and (
        not isinstance(image_variant, str) or image_variant not in known_variants()
    ):
        raise validation_error(
            f"image_variant must be one of {sorted(known_variants())}",
            field="image_variant",
        )
    if mem_limit is not None and not isinstance(mem_limit, str):
        raise validation_error("mem_limit must be a string like '512m'", field="mem_limit")
    if cpus is not None and (isinstance(cpus, bool) or not isinstance(cpus, (int, float))):
        raise validation_error("cpus must be a number", field="cpus")
    # Bounds-check explicit values; field_prefix="" puts errors on the bare
    # field names, matching this endpoint's wire shape.
    resolve_resource_limits(
        variant=image_variant or "full",
        requested_mem_limit=mem_limit,
        requested_cpus=float(cpus) if cpus is not None else None,
        settings=settings,
        field_prefix="",
    )
    if image_variant is not None:
        assert_config_runnable_on_variant(
            variant=image_variant, driver_name=driver, tool_names=tool_names,
            drivers=DRIVERS, tools=TOOLS,
        )
    return {
        "image_variant": image_variant,
        "mem_limit": mem_limit,
        "cpus": float(cpus) if cpus is not None else None,
    }


def template_public_view(row: dict[str, Any]) -> dict[str, Any]:
    """Enrich a raw DB row with driver metadata for the frontend editor."""
    driver_name = row["driver"]
    driver = DRIVERS.get(driver_name)

    capabilities: dict[str, Any] | None = None
    driver_template: dict[str, Any] | None = None
    available_tool_specs: list[dict[str, Any]] = []

    if driver is not None:
        capabilities = asdict(driver.capabilities)
        driver_template = asdict(driver.default_template)
        # Collect ToolSpec dicts for tools listed in the driver's default_template
        for tool_name in driver.default_template.available_tools:
            tool = TOOLS.get(tool_name)
            if tool is not None:
                available_tool_specs.append(asdict(tool.spec))

    return {
        **row,
        "context": context_view(row.get("context")),
        "capabilities": capabilities,
        "driver_template": driver_template,
        "available_tool_specs": available_tool_specs,
    }


def response_list(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a list of TemplateOut dicts into the spec envelope."""
    return {"templates": items}


def ensure_mutable_template(row: dict[str, Any]) -> None:
    """Raise APIError if the template is a built-in (read-only)."""
    if row.get("is_builtin"):
        raise APIError(
            409,
            "validation_error",
            "built-in templates are read-only; clone first",
            field="id",
        )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    response_description="Built-in and tenant-owned templates, driver-enriched.",
)
async def list_templates(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """List templates visible to the caller (spec §4.9, §7).

    Tenant-scoped read (any authenticated member/API key). Returns the global
    built-in templates (one per driver, read-only) plus the tenant's own. Each
    row is enriched with the driver's capabilities, default driver template and
    available tool specs so the console editor can stay within the driver
    envelope.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(templates).where(
                or_(
                    templates.c.is_builtin.is_(True),
                    templates.c.tenant_id == principal.tenant_id,
                )
            )
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    return response_list([template_public_view(r) for r in rows])


@router.get(
    "/templates/{template_id}",
    response_description="The driver-enriched template.",
)
async def get_template(
    template_id: Annotated[str, Path(description="Template id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Fetch a single template by id.

    Tenant-scoped read (any authenticated member/API key). Resolves against the
    global built-ins and the tenant's own templates; a template owned by another
    tenant is treated as absent. Enriched with driver metadata like the list
    endpoint. Returns ``404 not_found`` if no such template is visible.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(templates).where(
                templates.c.id == template_id,
                or_(
                    templates.c.is_builtin.is_(True),
                    templates.c.tenant_id == principal.tenant_id,
                ),
            )
        )
        row = result.fetchone()
    if row is None:
        raise not_found("template not found")
    return template_public_view(dict(row._mapping))


@router.post(
    "/templates",
    response_description="The created, driver-enriched template.",
)
async def create_template(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Create a tenant-scoped template (spec §4.9, §7).

    Admin-only. Body requires ``name`` and ``driver``; optional ``model``,
    ``effort``, ``system_prompt``, ``system_prompt_mode`` (default ``augment``), ``tools``,
    ``context``, ``skills``, ``mcp_servers``, ``limits``, ``image_variant``,
    ``mem_limit``, and ``cpus`` (the latter three are nullable). The new template
    is always non-built-in and owned by the caller's tenant. Errors: ``403
    forbidden`` for a staff principal with no tenant (built-ins are global and
    cannot be created this way); ``400 validation_error`` if the ``driver`` is
    unknown, ``image_variant`` is not recognized, or ``mem_limit``/``cpus`` are
    out of bounds; ``409 validation_error`` if a slim variant is combined with
    chromium-requiring tools.
    """
    # Templates are tenant-scoped (DB CHECK: is_builtin ⟺ tenant_id IS NULL).
    # A staff principal has tenant_id=None; let them fail cleanly here rather
    # than tripping the DB constraint with a 500.
    if principal.tenant_id is None:
        raise api_error(
            403, "forbidden",
            "Templates are tenant-scoped; staff have no tenant to own one",
        )
    body: dict[str, Any] = await request.json()

    new_row: dict[str, Any] = {
        "id": new_template_id(),
        "tenant_id": principal.tenant_id,
        "name": body["name"],
        "driver": body["driver"],
        "model": body.get("model"),
        "effort": body.get("effort"),
        "system_prompt": body.get("system_prompt", ""),
        "system_prompt_mode": body.get("system_prompt_mode", "augment"),
        "tools": body.get("tools", []),
        "context": context_from_body(body.get("context")),
        "skills": body.get("skills", []),
        "mcp_servers": body.get("mcp_servers", []),
        "limits": body.get("limits", {}),
        "is_builtin": False,
        "created_by": principal.user_id,
    }

    if new_row["driver"] not in DRIVERS:
        raise validation_error(f"unknown driver: {new_row['driver']!r}", field="driver")

    new_row.update(validate_template_runtime(
        image_variant=body.get("image_variant"),
        mem_limit=body.get("mem_limit"),
        cpus=body.get("cpus"),
        driver=new_row["driver"],
        tool_names=list(new_row["tools"] or []),
        settings=request.app.state.settings,
    ))

    async with request.app.state.session_factory() as session:
        await session.execute(templates.insert().values(**new_row))
        await session.commit()

    return template_public_view(new_row)


@router.patch(
    "/templates/{template_id}",
    response_description="The updated, driver-enriched template.",
)
async def patch_template(
    template_id: Annotated[str, Path(description="Template id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Update a tenant-owned template (partial patch).

    Admin-only. Only these fields are honoured; any others in the body are
    ignored: ``name``, ``driver``, ``model``, ``effort``, ``system_prompt``,
    ``system_prompt_mode``, ``tools``, ``context``, ``skills``, ``mcp_servers``,
    ``limits``, ``image_variant``, ``mem_limit``, ``cpus`` (the latter three are
    nullable). Errors: ``404 not_found`` if the template is not visible to the
    tenant; ``400 validation_error`` if ``image_variant`` is not recognized or
    ``mem_limit``/``cpus`` are out of bounds; ``409 validation_error`` if it is a
    read-only built-in (clone it first) or a slim variant is combined with
    chromium-requiring tools.
    """
    body: dict[str, Any] = await request.json()

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(templates).where(
                templates.c.id == template_id,
                or_(
                    templates.c.is_builtin.is_(True),
                    templates.c.tenant_id == principal.tenant_id,
                ),
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("template not found")

        row_dict = dict(row._mapping)
        ensure_mutable_template(row_dict)

        allowed_fields = {
            "name", "driver", "model", "effort", "system_prompt",
            "system_prompt_mode", "tools", "context", "skills", "mcp_servers", "limits",
            "image_variant", "mem_limit", "cpus",
        }
        updates = {k: v for k, v in body.items() if k in allowed_fields}
        if "context" in updates:
            updates["context"] = context_from_body(updates["context"])
        # Re-validate the runtime triple whenever any input to it changes —
        # including tools/driver patches against a stored slim variant.
        if {"image_variant", "mem_limit", "cpus", "tools", "driver"} & updates.keys():
            merged = {**row_dict, **updates}
            validated = validate_template_runtime(
                image_variant=merged.get("image_variant"),
                mem_limit=merged.get("mem_limit"),
                cpus=merged.get("cpus"),
                driver=merged["driver"],
                tool_names=list(merged["tools"] or []),
                settings=request.app.state.settings,
            )
            for key in ("image_variant", "mem_limit", "cpus"):
                if key in updates:
                    updates[key] = validated[key]
        if updates:
            await session.execute(
                templates.update()
                .where(templates.c.id == template_id)
                .values(**updates)
            )
            await session.commit()
            row_dict.update(updates)

    return template_public_view(row_dict)


@router.post(
    "/templates/{template_id}/clone",
    response_description="The newly created clone, driver-enriched.",
)
async def clone_template(
    template_id: Annotated[str, Path(description="Id of the template to clone.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Clone a template into a new tenant-owned copy (spec §4.9, §7).

    Tenant-scoped write (any authenticated member/API key; no admin gate) — this
    is how a read-only built-in is made editable. The source may be a built-in
    or one of the tenant's own templates. Optional body ``name`` sets the copy's
    name (default ``"Copy of <source name>"``); all other config fields are
    copied from the source. The clone is always non-built-in and owned by the
    caller's tenant. Errors: ``403 forbidden`` for a staff principal with no
    tenant; ``404 not_found`` if the source template is not visible.
    """
    # A clone is owned by the caller's tenant; staff (tenant_id=None) can't own
    # one — fail cleanly instead of tripping the DB CHECK constraint (500).
    if principal.tenant_id is None:
        raise api_error(
            403, "forbidden",
            "Templates are tenant-scoped; staff have no tenant to own one",
        )
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        pass

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(templates).where(
                templates.c.id == template_id,
                or_(
                    templates.c.is_builtin.is_(True),
                    templates.c.tenant_id == principal.tenant_id,
                ),
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("template not found")

        source = dict(row._mapping)
        clone_name = body.get("name", f"Copy of {source['name']}")

        new_row: dict[str, Any] = {
            "id": new_template_id(),
            "tenant_id": principal.tenant_id,
            "name": clone_name,
            "driver": source["driver"],
            "model": source.get("model"),
            "effort": source.get("effort"),
            "system_prompt": source["system_prompt"],
            "system_prompt_mode": source["system_prompt_mode"],
            "tools": source["tools"],
            # Lenient: cloning a legacy sparse/malformed source still succeeds,
            # and the clone is stored full-shape.
            "context": context_view(source["context"]),
            "skills": source.get("skills", []),
            "mcp_servers": source.get("mcp_servers", []),
            "limits": source["limits"],
            "image_variant": source.get("image_variant"),
            "mem_limit": source.get("mem_limit"),
            "cpus": source.get("cpus"),
            "is_builtin": False,
            "created_by": principal.user_id,
        }
        await session.execute(templates.insert().values(**new_row))
        await session.commit()

    return template_public_view(new_row)


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    response_description="Template deleted; no content returned.",
)
async def delete_template(
    template_id: Annotated[str, Path(description="Template id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> None:
    """Delete a tenant-owned template by id.

    Admin-only and tenant-scoped: only templates owned by the caller's tenant
    are matched (built-ins are never selected here). Returns ``204 No Content``
    on success. Errors: ``404 not_found`` if no such tenant template exists;
    ``409 validation_error`` if it is a read-only built-in.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(templates).where(
                templates.c.id == template_id,
                templates.c.tenant_id == principal.tenant_id,
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("template not found")

        ensure_mutable_template(dict(row._mapping))

        await session.execute(
            templates.delete().where(templates.c.id == template_id)
        )
        await session.commit()
