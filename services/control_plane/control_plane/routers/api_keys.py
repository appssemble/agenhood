from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.passwords import hash_password
from control_plane.auth.principal import Principal, actor_type_for, require_session_admin
from control_plane.auth.tokens import generate_api_key
from control_plane.errors import api_error
from control_plane.ids_compat import new_id

router = APIRouter(prefix="/v1/api-keys", tags=["API Keys"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class CreateKey(BaseModel):
    name: Annotated[
        str,
        Field(description="Human-readable label for the new API key, shown in listings."),
    ]


class ApiKeyView(BaseModel):
    """Public, non-secret view of an API key (never includes the token)."""

    id: Annotated[str, Field(description="Opaque API key id (prefixed `key_`).")]
    name: Annotated[str, Field(description="Human-readable label given at creation.")]
    prefix: Annotated[
        str,
        Field(description="Non-secret key prefix, shown to help identify the key."),
    ]
    created_by: Annotated[
        str | None,
        Field(description="User id of the session user who created the key, if known."),
    ]
    last_used_at: Annotated[
        datetime | None,
        Field(description="When the key was last used to authenticate, or null if never."),
    ]
    created_at: Annotated[datetime, Field(description="When the key was created (UTC).")]
    status: Annotated[
        str,
        Field(description="Key lifecycle status: `active` or `revoked`."),
    ]


class ApiKeyList(BaseModel):
    """Wrapper for the list-keys response."""

    keys: Annotated[
        list[ApiKeyView],
        Field(description="All API keys owned by the caller's tenant."),
    ]


class ApiKeyCreated(ApiKeyView):
    """Create-key response: the public view plus the one-time plaintext token."""

    key: Annotated[
        str,
        Field(
            description=(
                "The full plaintext API key. Returned EXACTLY ONCE at creation and "
                "never retrievable again — store it securely."
            )
        ),
    ]


class RevokeResult(BaseModel):
    """Result of revoking an API key."""

    id: Annotated[str, Field(description="Id of the revoked API key.")]
    status: Annotated[str, Field(description="Always `revoked` on success.")]


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


@router.get("", response_model=ApiKeyList, response_description="The tenant's API keys.")
async def list_keys(
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List the calling tenant's API keys (no secrets).

    Requires a tenant-scoped admin/owner **user session** (an API key principal
    cannot manage keys — spec §4.2). Staff must have an active tenant selected
    (impersonation) — they then act as that tenant's owner, same as the create
    and revoke endpoints. Only non-secret metadata is returned; the plaintext
    token is never included.

    Errors: 400 `validation_error` if the session has no active tenant (staff
    without a selected workspace); 403 if the caller is not a tenant
    admin/owner or authenticates with an API key instead of a session.
    """
    if p.tenant_id is None:
        raise api_error(400, "validation_error",
                        "Select a workspace to view its API keys")
    rows = (
        await conn.execute(
            sa.select(t.api_keys).where(t.api_keys.c.tenant_id == p.tenant_id)
        )
    ).mappings().all()
    return {"keys": [public_view(dict(r)) for r in rows]}


@router.post(
    "",
    status_code=201,
    response_model=ApiKeyCreated,
    response_description=(
        "The created key's metadata plus the one-time plaintext token in `key`."
    ),
)
async def create_key(
    body: CreateKey,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Create a tenant API key and reveal its plaintext token once.

    Requires a tenant-scoped admin/owner **user session** (spec §4.2). Mints a
    new key for the caller's tenant, stores only its Argon2id hash, and writes
    an `api_key.create` audit entry.

    Side effect / one-time reveal: the full plaintext key is returned in `key`
    EXACTLY ONCE in this response and can never be retrieved again — the server
    keeps only the hash.

    Errors: 400 `validation_error` if the session has no active tenant; 403 if
    the caller is not a tenant admin/owner or uses an API key instead of a
    session.
    """
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


@router.delete(
    "/{kid}",
    response_model=RevokeResult,
    response_description="The revoked key's id and its new `revoked` status.",
)
async def revoke_key(
    kid: Annotated[str, Path(description="Id of the API key to revoke (`key_` prefix).")],
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Revoke an API key (destructive, irreversible).

    Requires a tenant-scoped admin/owner **user session**; staff may revoke any
    tenant's key. Marks the key `revoked` and stamps `revoked_at`, immediately
    disabling all authentication with it, and writes an `api_key.revoke` audit
    entry. There is no un-revoke.

    Errors: 404 `not_found` if the key does not exist or belongs to another
    tenant (non-staff callers); 403 if the caller is not a tenant admin/owner or
    uses an API key instead of a session.
    """
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
