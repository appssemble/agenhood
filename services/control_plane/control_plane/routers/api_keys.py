from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.passwords import hash_password
from control_plane.auth.principal import Principal, actor_type_for, require_session_admin
from control_plane.auth.tokens import generate_api_key
from control_plane.errors import api_error
from control_plane.ids_compat import new_id

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class CreateKey(BaseModel):
    name: str


def build_api_key_row(
    *, tenant_id: str, name: str, created_by: str | None
) -> tuple[str, dict]:  # type: ignore[type-arg]
    secret, prefix = generate_api_key()
    row: dict = {  # type: ignore[type-arg]
        "id": new_id("key"),
        "tenant_id": tenant_id,
        "name": name,
        "key_hash": hash_password(secret),   # Argon2id (spec §4.3)
        "key_prefix": prefix,
        "created_by": created_by,
        "last_used_at": None,
        "status": "active",
        "revoked_at": None,
        "created_at": datetime.now(UTC),
    }
    return secret, row


def public_view(row: dict) -> dict:  # type: ignore[type-arg]
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["key_prefix"],
        "created_by": row["created_by"],
        "last_used_at": row["last_used_at"],
        "created_at": row["created_at"],
        "status": row["status"],
    }


@router.get("")
async def list_keys(
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if p.is_staff:
        raise api_error(400, "validation_error",
                        "Staff manage tenant keys via the tenant's own session")
    rows = (
        await conn.execute(
            sa.select(t.api_keys).where(t.api_keys.c.tenant_id == p.tenant_id)
        )
    ).mappings().all()
    return {"keys": [public_view(dict(r)) for r in rows]}


@router.post("", status_code=201)
async def create_key(
    body: CreateKey,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "An API key belongs to a tenant")
    secret, row = build_api_key_row(
        tenant_id=p.tenant_id, name=body.name, created_by=p.user_id
    )
    await conn.execute(sa.insert(t.api_keys).values(**row))
    await audit(
        conn,
        actor_type="tenant",
        actor_id=p.user_id,
        action="api_key.create",
        target_type="api_key",
        target_id=row["key_prefix"],
        details={"name": body.name},
    )
    await conn.commit()
    # One-time reveal: the full key is returned exactly once under `key`.
    return {**public_view(row), "key": secret}


@router.delete("/{kid}")
async def revoke_key(
    kid: str,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = (
        await conn.execute(sa.select(t.api_keys).where(t.api_keys.c.id == kid))
    ).mappings().first()
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "API key not found")
    await conn.execute(
        sa.update(t.api_keys).where(t.api_keys.c.id == kid).values(
            status="revoked", revoked_at=datetime.now(UTC)
        )
    )
    await audit(
        conn,
        actor_type=actor_type_for(p),
        actor_id=p.user_id,
        action="api_key.revoke",
        target_type="api_key",
        target_id=row["key_prefix"],
        details={"key_id": kid},
    )
    await conn.commit()
    return {"id": kid, "status": "revoked"}
