from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.auth.passwords import verify_password
from control_plane.auth.sessions import validate_and_slide
from control_plane.auth.tokens import API_KEY_PREFIX_LEN, hash_token
from control_plane.errors import api_error

Role = Literal["owner", "admin", "member"]
SESSION_COOKIE = "agent_session"


@dataclass(frozen=True)
class Principal:
    tenant_id: str | None       # the ACTIVE tenant for this request (None for staff/limbo)
    role: Role                  # role WITHIN the active tenant
    is_staff: bool
    user_id: str | None         # None for API keys and bootstrap key
    available_tenant_ids: tuple[str, ...] = ()   # tenants this user may switch to


def actor_type_for(principal: Principal) -> str:
    """Audit actor_type for a principal: 'admin' for staff, else 'tenant'."""
    return "admin" if principal.is_staff else "tenant"


class PrincipalRepo(Protocol):
    async def get_active_api_keys_by_prefix(self, prefix: str) -> list[dict]: ...  # type: ignore[type-arg]
    async def get_session_by_token_hash(self, token_hash: str) -> dict | None: ...  # type: ignore[type-arg]
    async def get_user(self, user_id: str) -> dict | None: ...  # type: ignore[type-arg]
    async def get_active_memberships(self, user_id: str) -> list[dict]: ...  # type: ignore[type-arg]
    async def tenant_exists(self, tenant_id: str) -> bool: ...
    async def touch_api_key(self, key_id: str) -> None: ...
    async def persist_session_slide(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None: ...


async def resolve_from_inputs(
    repo: PrincipalRepo,
    *,
    authorization: str | None,
    cookie_token: str | None,
    admin_api_key_env: str | None,
    at: datetime | None = None,
) -> Principal | None:
    at = at or datetime.now(UTC)
    bearer: str | None = None
    if authorization and authorization.startswith("Bearer "):
        bearer = authorization[len("Bearer "):].strip()

    # 1. Bootstrap admin key (break-glass, staff). Constant-time compare.
    if bearer and admin_api_key_env and secrets.compare_digest(bearer, admin_api_key_env):
        return Principal(tenant_id=None, role="member", is_staff=True, user_id=None)

    # 2. Tenant API key → member capability.
    if bearer and bearer.startswith("tk_live_"):
        prefix = bearer[:API_KEY_PREFIX_LEN]
        candidates = await repo.get_active_api_keys_by_prefix(prefix)
        for row in candidates:
            if verify_password(bearer, row["key_hash"]):
                await repo.touch_api_key(row["id"])
                return Principal(tenant_id=row["tenant_id"], role="member",
                                 is_staff=False, user_id=None)
        return None  # no matching key found

    # 3. Session cookie → user/staff principal.
    if cookie_token:
        srow = await repo.get_session_by_token_hash(hash_token(cookie_token))
        if not srow:
            return None
        slid = validate_and_slide(srow, at=at)
        if slid is None:
            return None
        user = await repo.get_user(srow["user_id"])
        if not user or user["status"] != "active":
            return None
        await repo.persist_session_slide(srow["id"], slid["last_seen_at"], slid["expires_at"])
        if user["is_staff"]:
            active = srow.get("active_tenant_id")
            if active is not None and await repo.tenant_exists(active):
                # Staff impersonation: scope into the tenant with full access,
                # but retain staff powers (is_staff stays True).
                return Principal(tenant_id=active, role="owner", is_staff=True,
                                 user_id=user["id"])
            return Principal(tenant_id=None, role="member", is_staff=True, user_id=user["id"])
        memberships = await repo.get_active_memberships(user["id"])
        by_tid = {m["tenant_id"]: m for m in memberships}
        available = tuple(by_tid.keys())
        active = srow.get("active_tenant_id")
        if active is not None and active in by_tid:
            return Principal(
                tenant_id=active, role=by_tid[active]["role"], is_staff=False,
                user_id=user["id"], available_tenant_ids=available,
            )
        # Limbo: no/invalid active tenant. /me and /select-tenant still work. Safety
        # comes from role gates: limbo has role="member"/is_staff=False, so it fails
        # require_admin/require_session_admin/require_staff; tenant-scoped mutations
        # are gated by those. (Some read endpoints additionally filter by tenant_id.)
        return Principal(
            tenant_id=None, role="member", is_staff=False,
            user_id=user["id"], available_tenant_ids=available,
        )

    return None


# ---------------------------------------------------------------------------
# DB-backed repo
# ---------------------------------------------------------------------------

class DbPrincipalRepo:
    def __init__(self, conn: AsyncSession) -> None:
        self._c = conn

    async def get_active_api_keys_by_prefix(self, prefix: str) -> list[dict]:  # type: ignore[type-arg]
        q = sa.select(t.api_keys).where(
            t.api_keys.c.key_prefix == prefix, t.api_keys.c.status == "active")
        rows = (await self._c.execute(q)).mappings().all()
        return [dict(r) for r in rows]

    async def get_session_by_token_hash(self, token_hash: str) -> dict | None:  # type: ignore[type-arg]
        q = sa.select(t.sessions).where(t.sessions.c.token_hash == token_hash)
        r = (await self._c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def get_user(self, user_id: str) -> dict | None:  # type: ignore[type-arg]
        q = sa.select(t.users).where(t.users.c.id == user_id)
        r = (await self._c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def get_active_memberships(self, user_id: str) -> list[dict]:  # type: ignore[type-arg]
        q = sa.select(t.memberships.c.tenant_id, t.memberships.c.role).where(
            t.memberships.c.user_id == user_id,
            t.memberships.c.status == "active",
        ).order_by(t.memberships.c.tenant_id)
        rows = (await self._c.execute(q)).mappings().all()
        return [dict(r) for r in rows]

    async def tenant_exists(self, tenant_id: str) -> bool:
        q = sa.select(t.tenants.c.id).where(t.tenants.c.id == tenant_id)
        return (await self._c.execute(q)).first() is not None

    async def touch_api_key(self, key_id: str) -> None:
        await self._c.execute(
            sa.update(t.api_keys)
            .where(t.api_keys.c.id == key_id)
            .values(last_used_at=datetime.now(UTC))
        )

    async def persist_session_slide(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        await self._c.execute(
            sa.update(t.sessions)
            .where(t.sessions.c.id == session_id)
            .values(last_seen_at=last_seen_at, expires_at=expires_at)
        )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def resolve_principal(
    request: Request,
    authorization: str | None = Header(
        default=None,
        description=(
            "Bearer token for authentication: a tenant API key (`tk_live_…`) or a "
            "session token, sent as `Authorization: Bearer <token>`. The console may "
            "authenticate via the session cookie instead."
        ),
    ),
) -> Principal:
    from sqlalchemy.ext.asyncio import async_sessionmaker  # local to avoid circular at module load

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    settings = request.app.state.settings
    cookie_token: str | None = request.cookies.get(SESSION_COOKIE)
    admin_api_key_env: str | None = getattr(settings, "admin_api_key", None)

    async with factory() as conn:
        repo = DbPrincipalRepo(conn)
        p = await resolve_from_inputs(
            repo,
            authorization=authorization,
            cookie_token=cookie_token,
            admin_api_key_env=admin_api_key_env,
        )

    if p is None:
        raise api_error(401, "unauthorized", "Authentication required")
    return p


# ---------------------------------------------------------------------------
# Role-gate helpers
# ---------------------------------------------------------------------------

def require_admin(principal: Principal = Depends(resolve_principal)) -> Principal:
    """admin or owner within a tenant, or staff. Session-only routes also use
    require_session_admin below where API keys must be rejected."""
    if principal.is_staff:
        return principal
    if principal.role in ("admin", "owner"):
        return principal
    raise api_error(403, "forbidden", "Admin role required")


def require_session_admin(principal: Principal = Depends(resolve_principal)) -> Principal:
    """User/API-key management is session-only (spec §4.2): an API key cannot
    mint keys or manage users. API-key principals have user_id is None and
    are not staff."""
    if principal.is_staff:
        return principal
    if principal.user_id is None:
        raise api_error(403, "forbidden", "This action requires a user session, not an API key")
    if principal.role in ("admin", "owner"):
        return principal
    raise api_error(403, "forbidden", "Admin role required")


def require_staff(principal: Principal = Depends(resolve_principal)) -> Principal:
    if not principal.is_staff:
        raise api_error(403, "forbidden", "Staff only")
    return principal
