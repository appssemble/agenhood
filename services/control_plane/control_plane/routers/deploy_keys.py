"""Workspace-scoped SSH deploy keys for private git skill sources.

Writes are admin-gated; reads are tenant-scoped. The private key is generated
server-side, stored AES-GCM-encrypted, and is never part of any response.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select

from control_plane.auth.crypto import load_key_from_env
from control_plane.auth.principal import Principal, require_admin
from control_plane.deploy_keys_service import (
    build_deploy_key_row,
    deploy_key_public_view,
)
from control_plane.errors import api_error, not_found
from control_plane.models_db import deploy_keys, skills

router = APIRouter(tags=["Deploy keys"])


@router.post("/deploy-keys", status_code=201,
             response_description="The created key's public half.")
async def create_deploy_key(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Generate a new Ed25519 deploy key for this workspace.

    Returns only the public key + fingerprint — install the public key as a
    read-only deploy key on the private repository. The private half is stored
    encrypted and never returned. Errors: ``409 conflict`` on a duplicate name.
    """
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "Deploy keys are tenant-scoped")
    body = await request.json()
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise api_error(400, "validation_error", "name is required", "name")
    master_key = load_key_from_env()
    try:
        row = build_deploy_key_row(
            tenant_id=principal.tenant_id, name=name,
            master_key=master_key,
        )
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "name") from exc
    async with request.app.state.session_factory() as session:
        dupe = await session.execute(
            select(deploy_keys.c.id).where(
                deploy_keys.c.tenant_id == principal.tenant_id,
                deploy_keys.c.name == row["name"],
            )
        )
        if dupe.first() is not None:
            raise api_error(409, "conflict", f"deploy key {row['name']!r} already exists")
        await session.execute(deploy_keys.insert().values(**row))
        await session.commit()
    return deploy_key_public_view(row)


@router.get("/deploy-keys", response_description="The workspace's deploy keys.")
async def list_deploy_keys(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """List this workspace's deploy keys (public halves only)."""
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "Deploy keys are tenant-scoped")
    async with request.app.state.session_factory() as session:
        rows = await session.execute(
            select(deploy_keys)
            .where(deploy_keys.c.tenant_id == principal.tenant_id)
            .order_by(deploy_keys.c.name)
        )
        views = [deploy_key_public_view(dict(r._mapping)) for r in rows.fetchall()]
    return {"deploy_keys": views}


@router.delete("/deploy-keys/{dkid}", response_description="Deletion confirmation.")
async def delete_deploy_key(
    dkid: Annotated[str, Path(description="Deploy key id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Delete a deploy key. Refused (409) while any skill still uses it."""
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "Deploy keys are tenant-scoped")
    async with request.app.state.session_factory() as session:
        row = (await session.execute(
            select(deploy_keys.c.id).where(
                deploy_keys.c.id == dkid,
                deploy_keys.c.tenant_id == principal.tenant_id,
            )
        )).first()
        if row is None:
            raise not_found("deploy key not found")
        users = (await session.execute(
            select(skills.c.name).where(skills.c.deploy_key_id == dkid)
        )).fetchall()
        if users:
            names = ", ".join(sorted(r[0] for r in users))
            raise api_error(
                409, "deploy_key_in_use",
                f"deploy key is used by skill(s): {names}",
            )
        await session.execute(deploy_keys.delete().where(deploy_keys.c.id == dkid))
        await session.commit()
    return {"ok": True}
