from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.passwords import verify_password
from control_plane.auth.principal import SESSION_COOKIE, Principal, resolve_principal
from control_plane.auth.sessions import build_session_row
from control_plane.auth.tokens import hash_token
from control_plane.errors import api_error
from control_plane.membership_service import default_active_tenant
from control_plane.tenant_defaults import merge_limits

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# Session dependency (mirrors containers._session pattern)
# ---------------------------------------------------------------------------

async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr = Field(
        description=(
            "Account email address. Case-insensitive; normalized to lowercase before lookup."
        ),
    )
    password: str = Field(
        description=(
            "Account password. Sent as a secret and never echoed back, even in a 422 "
            "validation error."
        ),
    )

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class SelectTenantRequest(BaseModel):
    tenant_id: str | None = Field(
        default=None,
        description=(
            "Workspace (tenant) to activate for the current session. Members must pass a "
            "tenant they actively belong to. Staff may pass any existing tenant to impersonate "
            "it, or null to clear back to the cross-tenant (unscoped) state."
        ),
    )


class SelectTenantResponse(BaseModel):
    active_tenant_id: str | None = Field(
        description=(
            "The tenant now active on the session, or null when a staff caller cleared "
            "their selection."
        ),
    )
    role: str | None = Field(
        description=(
            "The caller's role in the active tenant (owner/admin/member), or null when no "
            "tenant is active."
        ),
    )


class LogoutResponse(BaseModel):
    ok: bool = Field(
        description="Always true; the session (if any) was revoked and the cookie cleared."
    )


def build_login_response(
    user: dict,  # type: ignore[type-arg]
    *,
    active_tenant_id: str | None,
    tenants: list[dict],  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    active_role = next(
        (m["role"] for m in tenants if m["id"] == active_tenant_id), None
    )
    return {
        "id": user["id"],
        "role": active_role,
        "name": user["name"],
        "must_change_password": user["must_change_password"],
        "active_tenant_id": active_tenant_id,
        "tenants": tenants,
        "needs_tenant_selection": active_tenant_id is None and not user.get("is_staff", False),
    }


def build_me(
    user: dict,  # type: ignore[type-arg]
    tenant: dict | None,  # type: ignore[type-arg]
    *,
    active_tenant_id: str | None,
    tenants: list[dict],  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Serialize /me for a user principal.

    `tenant` is the *active* tenant (id/name/limits) so the console can populate
    the allowed-models / allowed-drivers pickers; `tenants` is the switcher list.
    """
    tenant_view: dict | None = None  # type: ignore[type-arg]
    if tenant is not None:
        # Report *effective* limits so the console's allowed-drivers / allowed-models
        # pickers reflect the current platform defaults for any key the tenant did
        # not explicitly override (e.g. a newly added driver). See merge_limits.
        tenant_view = {
            "id": tenant["id"],
            "name": tenant["name"],
            "limits": merge_limits(tenant["limits"]),
        }
    return {
        "principal": "user",
        "id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "must_change_password": user["must_change_password"],
        "email": user["email"],
        "is_staff": user["is_staff"],
        "active_tenant_id": active_tenant_id,
        "tenant": tenant_view,
        "tenants": tenants,
    }


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------

def _set_cookie(resp: Response, token: str, secure: bool = True) -> None:
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_description=(
        "The authenticated user's profile plus tenant switcher list and resolved active tenant. "
        "An `HttpOnly` session cookie is set on the response."
    ),
)
async def login(
    body: LoginRequest,
    response: Response,
    request: Request,
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Authenticate with email + password and start a session.

    Unauthenticated endpoint. On success it creates a `sessions` row and sets an
    `HttpOnly`, `SameSite=Lax` session cookie (14-day sliding lifetime), then
    resolves the active tenant: staff resume their last-used (or first) workspace;
    members resume a workspace they still belong to, else their owner-first default.
    The response body carries the user profile, the tenant switcher list, and the
    resolved `active_tenant_id` / `needs_tenant_selection` hint.

    Attempts are rate-limited per email + client IP. Errors: 429 too_many_requests
    when the limiter trips; 401 unauthorized for an unknown email, wrong password,
    or an inactive account (the same message is returned for all, to avoid
    user-enumeration). The password is a secret and is never echoed back.
    """
    from control_plane.auth.ratelimit import login_limiter

    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{body.email}|{client_ip}"
    if not login_limiter.allow(rate_key):
        raise api_error(429, "too_many_requests", "Too many login attempts; try again later")

    q = sa.select(t.users).where(
        t.users.c.email == body.email,
        t.users.c.status == "active",
    )
    user_row = (await conn.execute(q)).mappings().first()
    # Always run verify to avoid user-enumeration timing side-channels.
    ok = user_row is not None and verify_password(body.password, user_row["password_hash"])
    if not ok or user_row is None:
        raise api_error(401, "unauthorized", "Invalid email or password")

    memberships = (
        await conn.execute(
            sa.select(t.memberships.c.tenant_id, t.memberships.c.role).where(
                t.memberships.c.user_id == user_row["id"],
                t.memberships.c.status == "active",
            ).order_by(t.memberships.c.tenant_id)
        )
    ).mappings().all()
    tenants = [{"id": m["tenant_id"], "role": m["role"]} for m in memberships]
    # Resume the most-recent prior session's selected tenant, where there is one.
    prior_tenant_id = (
        await conn.execute(
            sa.select(t.sessions.c.active_tenant_id)
            .where(
                t.sessions.c.user_id == user_row["id"],
                t.sessions.c.active_tenant_id.isnot(None),
            )
            .order_by(t.sessions.c.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    member_tids = {m["tenant_id"] for m in memberships}
    active_tenant_id: str | None = None
    if user_row["is_staff"]:
        # Staff are always scoped to a workspace (no cross-tenant "all" state):
        # resume their last (any existing tenant — staff may enter any), else their
        # first owned workspace, else the first tenant overall.
        if prior_tenant_id is not None and (
            await conn.execute(sa.select(t.tenants.c.id).where(t.tenants.c.id == prior_tenant_id))
        ).first() is not None:
            active_tenant_id = prior_tenant_id
        else:
            active_tenant_id = default_active_tenant(memberships) or (
                await conn.execute(sa.select(t.tenants.c.id).order_by(t.tenants.c.name).limit(1))
            ).scalar_one_or_none()
    elif member_tids:
        # Members resume only a tenant they still belong to, else owner-first default.
        active_tenant_id = (
            prior_tenant_id
            if prior_tenant_id in member_tids
            else default_active_tenant(memberships)
        )

    token, srow = build_session_row(user_id=user_row["id"])
    srow["active_tenant_id"] = active_tenant_id
    await conn.execute(sa.insert(t.sessions).values(**srow))
    await conn.commit()
    _set_cookie(response, token, secure=request.app.state.settings.session_cookie_secure)
    return build_login_response(dict(user_row), active_tenant_id=active_tenant_id, tenants=tenants)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    response_description="Confirmation that the session was revoked and the cookie cleared.",
)
async def logout(
    request: Request,
    response: Response,
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Revoke the current session and clear the session cookie.

    If a session cookie is present, its backing `sessions` row is marked revoked;
    the cookie is deleted regardless. Idempotent and safe to call without an active
    session (still returns `{"ok": true}`). No authentication is required.
    """
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        await conn.execute(
            sa.update(t.sessions)
            .where(t.sessions.c.token_hash == hash_token(cookie))
            .values(revoked_at=datetime.now(UTC))
        )
        await conn.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post(
    "/select-tenant",
    response_model=SelectTenantResponse,
    response_description="The now-active tenant id and the caller's role within it.",
)
async def select_tenant(
    body: SelectTenantRequest,
    request: Request,
    principal: Principal = Depends(resolve_principal),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Switch the active workspace (tenant) for the current session.

    Requires a valid user session (a session cookie or bearer session token);
    unauthenticated callers get 401. The selection is persisted on the `sessions`
    row so it survives reconnects.

    Staff may activate any existing tenant (audited as an impersonation) or pass
    `tenant_id: null` to clear back to the cross-tenant state (audited as an
    impersonation exit). Members must pass a tenant they are an active member of and
    cannot clear their selection.

    Errors: 401 unauthorized when unauthenticated; 403 forbidden for an API-key
    principal (no user session) or for a member who is not in the requested tenant;
    404 not_found when staff target a tenant that does not exist; 400
    validation_error when a member omits `tenant_id`.
    """
    if principal.user_id is None:
        raise api_error(403, "forbidden", "Tenant selection requires a user session")
    cookie = request.cookies.get(SESSION_COOKIE)

    async def _set_active(tenant_id: str | None) -> None:
        await conn.execute(
            sa.update(t.sessions)
            .where(t.sessions.c.token_hash == hash_token(cookie))
            .values(active_tenant_id=tenant_id)
        )

    # Staff: impersonate ANY existing tenant, or clear to cross-tenant.
    if principal.is_staff:
        if body.tenant_id is None:
            await _set_active(None)
            await audit(
                conn,
                actor_type="admin",
                actor_id=principal.user_id,
                action="staff.impersonate.exit",
                target_type="tenant",
                target_id=principal.tenant_id,
                details={"from_tenant_id": principal.tenant_id},
            )
            await conn.commit()
            return {"active_tenant_id": None, "role": None}
        exists = (
            await conn.execute(sa.select(t.tenants.c.id).where(t.tenants.c.id == body.tenant_id))
        ).first()
        if exists is None:
            raise api_error(404, "not_found", "Workspace not found", "tenant_id")
        await _set_active(body.tenant_id)
        await audit(
            conn,
            actor_type="admin",
            actor_id=principal.user_id,
            action="staff.impersonate",
            target_type="tenant",
            target_id=body.tenant_id,
            details={},
        )
        await conn.commit()
        return {"active_tenant_id": body.tenant_id, "role": "owner"}

    # Member: must select a tenant they actively belong to; cannot clear.
    if body.tenant_id is None:
        raise api_error(400, "validation_error", "A tenant_id is required", "tenant_id")
    m = (
        await conn.execute(
            sa.select(t.memberships.c.role).where(
                t.memberships.c.user_id == principal.user_id,
                t.memberships.c.tenant_id == body.tenant_id,
                t.memberships.c.status == "active",
            )
        )
    ).mappings().first()
    if m is None:
        raise api_error(403, "forbidden", "Not a member of that tenant")
    await _set_active(body.tenant_id)
    await conn.commit()
    return {"active_tenant_id": body.tenant_id, "role": m["role"]}


@router.get(
    "/me",
    response_description=(
        "Identity of the calling principal. User sessions return the full user profile with the "
        "active tenant and switcher list; API-key/staff-bootstrap principals return a compact "
        "`{principal, tenant_id, role, is_staff}` identity."
    ),
)
async def me(
    conn: AsyncSession = Depends(_session),
    principal: Principal = Depends(resolve_principal),
) -> dict:  # type: ignore[type-arg]
    """Return the identity of the authenticated caller.

    Requires a valid session cookie, session bearer token, or API key; otherwise
    401 unauthorized. For a user principal it returns the user profile (id, name,
    email, staff flag, must-change-password), the active tenant with its effective
    limits, the caller's role, and the tenant switcher list. For an API-key or
    bootstrap principal it returns a compact tenant identity instead.

    Error: 404 not_found if the session references a user that no longer exists.
    """
    if principal.user_id is None:
        # API key or bootstrap principal: return the tenant identity.
        return {
            "principal": "api_key" if not principal.is_staff else "staff",
            "tenant_id": principal.tenant_id,
            "role": principal.role,
            "is_staff": principal.is_staff,
        }
    u_row = (
        await conn.execute(sa.select(t.users).where(t.users.c.id == principal.user_id))
    ).mappings().first()
    if u_row is None:
        raise api_error(404, "not_found", "User not found")

    rows = (
        await conn.execute(
            sa.select(t.memberships.c.tenant_id, t.memberships.c.role, t.tenants.c.name)
            .select_from(
                t.memberships.join(t.tenants, t.memberships.c.tenant_id == t.tenants.c.id)
            )
            .where(
                t.memberships.c.user_id == principal.user_id,
                t.memberships.c.status == "active",
            )
            .order_by(t.memberships.c.tenant_id)
        )
    ).mappings().all()
    tenants = [{"id": r["tenant_id"], "name": r["name"], "role": r["role"]} for r in rows]

    active_tenant_id = principal.tenant_id
    active_role = principal.role
    tenant_row = None
    if active_tenant_id is not None:
        tenant_row = (
            await conn.execute(sa.select(t.tenants).where(t.tenants.c.id == active_tenant_id))
        ).mappings().first()

    user_view = {
        "id": u_row["id"], "name": u_row["name"], "email": u_row["email"],
        "is_staff": u_row["is_staff"], "must_change_password": u_row["must_change_password"],
        "role": active_role,
    }
    return build_me(
        user_view, dict(tenant_row) if tenant_row is not None else None,
        active_tenant_id=active_tenant_id, tenants=tenants,
    )
