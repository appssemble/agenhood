from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select

# Trigger driver + tool registration
import agentcore.drivers.vanilla  # noqa: F401
import agentcore.tools  # noqa: F401
from agentcore.drivers.base import DRIVERS
from agentcore.tools.base import TOOLS
from control_plane.auth.principal import Principal, require_admin, resolve_principal
from control_plane.errors import APIError, api_error, not_found, validation_error
from control_plane.ids import new_template_id
from control_plane.models_db import templates

router = APIRouter()


# ---------------------------------------------------------------------------
# Pure helpers (testable without DB)
# ---------------------------------------------------------------------------


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


@router.get("/templates")
async def list_templates(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
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


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
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


@router.post("/templates")
async def create_template(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
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
        "system_prompt": body.get("system_prompt", ""),
        "system_prompt_mode": body.get("system_prompt_mode", "augment"),
        "tools": body.get("tools", []),
        "context": body.get("context", {}),
        "skills": body.get("skills", []),
        "mcp_servers": body.get("mcp_servers", []),
        "limits": body.get("limits", {}),
        "is_builtin": False,
        "created_by": principal.user_id,
    }

    if new_row["driver"] not in DRIVERS:
        raise validation_error(f"unknown driver: {new_row['driver']!r}", field="driver")

    async with request.app.state.session_factory() as session:
        await session.execute(templates.insert().values(**new_row))
        await session.commit()

    return template_public_view(new_row)


@router.patch("/templates/{template_id}")
async def patch_template(
    template_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
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
            "name", "driver", "model", "system_prompt",
            "system_prompt_mode", "tools", "context", "skills", "mcp_servers", "limits",
        }
        updates = {k: v for k, v in body.items() if k in allowed_fields}
        if updates:
            await session.execute(
                templates.update()
                .where(templates.c.id == template_id)
                .values(**updates)
            )
            await session.commit()
            row_dict.update(updates)

    return template_public_view(row_dict)


@router.post("/templates/{template_id}/clone")
async def clone_template(
    template_id: str,
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
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
            "system_prompt": source["system_prompt"],
            "system_prompt_mode": source["system_prompt_mode"],
            "tools": source["tools"],
            "context": source["context"],
            "skills": source.get("skills", []),
            "mcp_servers": source.get("mcp_servers", []),
            "limits": source["limits"],
            "is_builtin": False,
            "created_by": principal.user_id,
        }
        await session.execute(templates.insert().values(**new_row))
        await session.commit()

    return template_public_view(new_row)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),
) -> None:
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
