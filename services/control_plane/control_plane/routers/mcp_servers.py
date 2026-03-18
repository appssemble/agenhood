"""Tenant MCP-server library CRUD. Reads are tenant-scoped; writes are
admin-gated. Mirrors routers/skills.py. The auth secret is encrypted at rest and
never returned (see mcp_service)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from control_plane.auth.crypto import encrypt_secret, load_key_from_env
from control_plane.auth.principal import Principal, require_admin, resolve_principal
from control_plane.errors import api_error, not_found
from control_plane.mcp_service import (
    build_mcp_row,
    mcp_detail_view,
    mcp_public_view,
    validate_mcp_fields,
)
from control_plane.models_db import mcp_servers
from control_plane.skills_service import normalize_description

router = APIRouter()

# secret_ciphertext is included solely to derive secret_set; it is never returned.
_ROW_COLS = [
    mcp_servers.c.id, mcp_servers.c.tenant_id, mcp_servers.c.name,
    mcp_servers.c.description, mcp_servers.c.url, mcp_servers.c.auth_type,
    mcp_servers.c.auth_header_name, mcp_servers.c.secret_ciphertext,
    mcp_servers.c.enabled, mcp_servers.c.created_by,
    mcp_servers.c.created_at, mcp_servers.c.updated_at,
]


def parse_mcp_create(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a create payload -> normalized field dict (incl. plaintext secret)."""
    name = body.get("name")
    description = body.get("description")
    url = body.get("url")
    if not isinstance(name, str):
        raise api_error(400, "validation_error", "name is required", "name")
    if not isinstance(description, str):
        raise api_error(400, "validation_error", "description is required", "description")
    if not isinstance(url, str):
        raise api_error(400, "validation_error", "url is required", "url")
    description = normalize_description(description)
    auth_type = body.get("auth_type", "none")
    auth_header_name = body.get("auth_header_name") or None
    secret = body.get("secret", "") or ""
    validate_mcp_fields(
        name=name, description=description, url=url, auth_type=auth_type,
        auth_header_name=auth_header_name, has_secret=bool(secret),
    )
    return {
        "name": name, "description": description, "url": url,
        "auth_type": auth_type, "auth_header_name": auth_header_name,
        "secret": secret, "enabled": bool(body.get("enabled", True)),
    }


def apply_mcp_patch(existing: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Merge a PATCH onto existing fields and re-validate. Returns (merged, directive)
    where directive is 'keep' | 'set' | 'clear' for the secret column."""
    merged = {k: existing.get(k) for k in
              ("name", "description", "url", "auth_type", "auth_header_name", "enabled")}
    for k in ("name", "description", "url", "auth_type", "auth_header_name", "enabled"):
        if k in patch:
            merged[k] = patch[k]
    if "description" in patch:
        merged["description"] = normalize_description(str(merged["description"]))
    merged["auth_header_name"] = merged["auth_header_name"] or None
    merged["enabled"] = bool(merged["enabled"])

    directive = "keep"
    if "secret" in patch:
        directive = "set" if patch["secret"] else "clear"
    will_have_secret = (
        directive == "set"
        or (directive == "keep" and existing.get("secret_ciphertext") is not None)
    )
    validate_mcp_fields(
        name=str(merged["name"]), description=str(merged["description"]),
        url=str(merged["url"]), auth_type=str(merged["auth_type"]),
        auth_header_name=merged["auth_header_name"], has_secret=will_have_secret,
    )
    if directive == "set":
        merged["secret"] = patch["secret"]
    return merged, directive


@router.get("/mcp-servers")
async def list_mcp_servers(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(mcp_servers.c.tenant_id == principal.tenant_id)
            .order_by(mcp_servers.c.name)
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    return {"mcp_servers": [mcp_public_view(r) for r in rows]}


@router.get("/mcp-servers/{mid}")
async def get_mcp_server(
    mid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(
                mcp_servers.c.id == mid, mcp_servers.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
    if row is None:
        raise not_found("mcp server not found")
    return mcp_detail_view(dict(row._mapping))


@router.post("/mcp-servers")
async def create_mcp_server(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "MCP servers are tenant-scoped")
    fields = parse_mcp_create(await request.json())
    row = build_mcp_row(
        tenant_id=principal.tenant_id, created_by=principal.user_id,
        name=fields["name"], description=fields["description"], url=fields["url"],
        auth_type=fields["auth_type"], auth_header_name=fields["auth_header_name"],
        secret=fields["secret"], enabled=fields["enabled"],
        master_key=load_key_from_env() if fields["secret"] else None,
    )
    async with request.app.state.session_factory() as session:
        dupe = await session.execute(
            select(mcp_servers.c.id).where(
                mcp_servers.c.tenant_id == principal.tenant_id,
                mcp_servers.c.name == row["name"],
            )
        )
        if dupe.fetchone() is not None:
            raise api_error(
                409, "conflict", f"an mcp server named {row['name']!r} already exists", "name"
            )
        await session.execute(mcp_servers.insert().values(**row))
        await session.commit()
    return mcp_detail_view(row)


@router.patch("/mcp-servers/{mid}")
async def patch_mcp_server(
    mid: str, request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    patch = await request.json()
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_ROW_COLS).where(
                mcp_servers.c.id == mid, mcp_servers.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("mcp server not found")
        existing = dict(row._mapping)
        merged, directive = apply_mcp_patch(existing, patch)
        if merged["name"] != existing["name"]:
            dupe = await session.execute(
                select(mcp_servers.c.id).where(
                    mcp_servers.c.tenant_id == principal.tenant_id,
                    mcp_servers.c.name == merged["name"],
                    mcp_servers.c.id != mid,
                )
            )
            if dupe.fetchone() is not None:
                raise api_error(
                    409, "conflict",
                    f"an mcp server named {merged['name']!r} already exists", "name",
                )
        values: dict[str, Any] = {
            "name": merged["name"], "description": merged["description"],
            "url": merged["url"], "auth_type": merged["auth_type"],
            "auth_header_name": merged["auth_header_name"], "enabled": merged["enabled"],
            "updated_at": datetime.now(UTC),
        }
        if directive == "set":
            values["secret_ciphertext"] = encrypt_secret(merged["secret"], load_key_from_env())
        elif directive == "clear":
            values["secret_ciphertext"] = None
        await session.execute(
            mcp_servers.update().where(mcp_servers.c.id == mid).values(**values)
        )
        await session.commit()
        existing.update(values)
    return mcp_detail_view(existing)


@router.delete("/mcp-servers/{mid}", status_code=204)
async def delete_mcp_server(
    mid: str, request: Request, principal: Principal = Depends(require_admin)
) -> None:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(mcp_servers.c.id).where(
                mcp_servers.c.id == mid, mcp_servers.c.tenant_id == principal.tenant_id
            )
        )
        if result.fetchone() is None:
            raise not_found("mcp server not found")
        await session.execute(mcp_servers.delete().where(mcp_servers.c.id == mid))
        await session.commit()
