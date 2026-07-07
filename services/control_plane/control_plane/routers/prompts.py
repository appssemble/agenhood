"""Tenant prompt-library CRUD. Reads AND writes are tenant-scoped (any member);
no admin gate. Mirrors routers/mcp_servers.py minus the secret handling."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from control_plane.auth.principal import Principal, resolve_principal
from control_plane.errors import api_error, not_found
from control_plane.models_db import prompts
from control_plane.prompts_service import (
    build_prompt_row,
    normalize_tags,
    prompt_view,
    reconcile_variables,
    validate_prompt_fields,
)

router = APIRouter(tags=["Prompts"])


# ---- response models (documentation only) -----------------------------------

class PromptListResponse(BaseModel):
    """Envelope returned by ``GET /prompts``."""

    prompts: list[dict[str, Any]] = Field(
        description="The tenant's prompts, each with body, tags and resolved "
        "variables. Sorted by name."
    )


_ROW_COLS = [
    prompts.c.id, prompts.c.tenant_id, prompts.c.name, prompts.c.body,
    prompts.c.tags, prompts.c.variables, prompts.c.created_by,
    prompts.c.created_at, prompts.c.updated_at,
]


def parse_prompt_create(body: dict[str, Any]) -> dict[str, Any]:
    name = body.get("name")
    text = body.get("body")
    if not isinstance(name, str):
        raise api_error(400, "validation_error", "name is required", "name")
    if not isinstance(text, str):
        raise api_error(400, "validation_error", "body is required", "body")
    tags = normalize_tags(body.get("tags"))
    validate_prompt_fields(name=name, body=text, tags=tags)
    return {
        "name": name,
        "body": text,
        "tags": tags,
        "variables": reconcile_variables(text, body.get("variables")),
    }


def apply_prompt_patch(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    name = patch["name"] if "name" in patch else existing["name"]
    text = patch["body"] if "body" in patch else existing["body"]
    if not isinstance(name, str):
        raise api_error(400, "validation_error", "name must be a string", "name")
    if not isinstance(text, str):
        raise api_error(400, "validation_error", "body must be a string", "body")
    tags = normalize_tags(patch["tags"]) if "tags" in patch else list(existing.get("tags") or [])
    validate_prompt_fields(name=name, body=text, tags=tags)
    # Reconcile against the patch's variables if supplied, else the existing metadata.
    meta = patch["variables"] if "variables" in patch else existing.get("variables")
    return {
        "name": name.strip(),
        "body": text,
        "tags": tags,
        "variables": reconcile_variables(text, meta),
    }


@router.get(
    "/prompts",
    response_model=PromptListResponse,
    response_description="The tenant's prompts.",
)
async def list_prompts(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """List all prompts owned by the caller's tenant.

    Tenant-scoped read (any authenticated member/API key; no admin gate). Sorted
    by name.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(prompts.c.tenant_id == principal.tenant_id)
            .order_by(prompts.c.name)
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    return {"prompts": [prompt_view(r) for r in rows]}


@router.get(
    "/prompts/{pid}",
    response_description="The prompt.",
)
async def get_prompt(
    pid: Annotated[str, Path(description="Prompt id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Fetch a single prompt by id.

    Tenant-scoped read (any authenticated member/API key; no admin gate); a
    prompt belonging to another tenant is treated as absent. Returns ``404
    not_found`` if no such prompt exists for the tenant.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(
                prompts.c.id == pid, prompts.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
    if row is None:
        raise not_found("prompt not found")
    return prompt_view(dict(row._mapping))


@router.post(
    "/prompts",
    response_description="The created prompt.",
)
async def create_prompt(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """Create a prompt for the caller's tenant.

    Tenant-scoped write (any authenticated member/API key; no admin gate). Body
    requires ``name`` and ``body``; optional ``tags`` and ``variables``. The
    ``{{name}}`` placeholders in the body are reconciled against the supplied
    variable metadata. Errors: ``403 forbidden`` for a staff principal with no
    tenant; ``400 validation_error`` for a malformed payload; ``409 conflict``
    if a prompt of that name already exists for the tenant.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "prompts are tenant-scoped")
    fields = parse_prompt_create(await request.json())
    row = build_prompt_row(
        tenant_id=principal.tenant_id, created_by=principal.user_id,
        name=fields["name"], body=fields["body"],
        tags=fields["tags"], variables=fields["variables"],
    )
    async with request.app.state.session_factory() as session:
        dupe = await session.execute(
            select(prompts.c.id).where(
                prompts.c.tenant_id == principal.tenant_id,
                prompts.c.name == row["name"],
            )
        )
        if dupe.fetchone() is not None:
            raise api_error(
                409, "conflict", f"a prompt named {row['name']!r} already exists", "name"
            )
        await session.execute(prompts.insert().values(**row))
        await session.commit()
    return prompt_view(row)


@router.patch(
    "/prompts/{pid}",
    response_description="The updated prompt.",
)
async def patch_prompt(
    pid: Annotated[str, Path(description="Prompt id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Update an existing prompt (partial patch).

    Tenant-scoped write (any authenticated member/API key; no admin gate). Any
    of ``name``, ``body``, ``tags`` and ``variables`` may be patched; omitted
    fields keep their current values. Variables are reconciled against the
    body's ``{{name}}`` placeholders. Errors: ``404 not_found`` if the prompt
    does not exist for the tenant; ``400 validation_error`` for a malformed
    field; ``409 conflict`` if a rename collides with another prompt's name.
    """
    patch = await request.json()
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(
                prompts.c.id == pid, prompts.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("prompt not found")
        existing = dict(row._mapping)
        merged = apply_prompt_patch(existing, patch)
        if merged["name"] != existing["name"]:
            dupe = await session.execute(
                select(prompts.c.id).where(
                    prompts.c.tenant_id == principal.tenant_id,
                    prompts.c.name == merged["name"],
                    prompts.c.id != pid,
                )
            )
            if dupe.fetchone() is not None:
                raise api_error(
                    409, "conflict",
                    f"a prompt named {merged['name']!r} already exists", "name",
                )
        values = {
            "name": merged["name"], "body": merged["body"],
            "tags": merged["tags"], "variables": merged["variables"],
            "updated_at": datetime.now(UTC),
        }
        await session.execute(
            prompts.update()
            .where(prompts.c.id == pid, prompts.c.tenant_id == principal.tenant_id)
            .values(**values)
        )
        await session.commit()
        existing.update(values)
    return prompt_view(existing)


@router.delete(
    "/prompts/{pid}",
    status_code=204,
    response_description="Prompt deleted; no content returned.",
)
async def delete_prompt(
    pid: Annotated[str, Path(description="Prompt id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> None:
    """Delete a prompt by id.

    Tenant-scoped write (any authenticated member/API key; no admin gate).
    Returns ``204 No Content`` on success. Returns ``404 not_found`` if no such
    prompt exists for the tenant.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(prompts.c.id).where(
                prompts.c.id == pid, prompts.c.tenant_id == principal.tenant_id
            )
        )
        if result.fetchone() is None:
            raise not_found("prompt not found")
        await session.execute(
            prompts.delete().where(
                prompts.c.id == pid, prompts.c.tenant_id == principal.tenant_id
            )
        )
        await session.commit()
