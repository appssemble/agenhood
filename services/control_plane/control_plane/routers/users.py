from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.passwords import hash_password, verify_password
from control_plane.auth.principal import (
    SESSION_COOKIE,
    Principal,
    actor_type_for,
    require_session_admin,
    resolve_principal,
)
from control_plane.auth.tokens import hash_token
from control_plane.errors import api_error
from control_plane.membership_service import new_membership_row, owner_conflict_message
from control_plane.users_service import (
    OwnerProtected,
    assert_can_disable_or_delete,
    assert_role_change_allowed,
    new_user_row,
)

router = APIRouter(prefix="/v1/users", tags=["users"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


def _tenant_scope(p: Principal, body_tenant: str | None = None) -> str:
    # Tenant admins are scoped to their own tenant. Staff target a tenant
    # explicitly via the request body, or implicitly via the tenant they're
    # impersonating (the active tenant on the principal). Error only when a
    # staff principal has neither.
    if p.is_staff:
        tid = body_tenant or p.tenant_id
        if not tid:
            raise api_error(400, "validation_error", "Staff must specify tenant_id", "tenant_id")
        return tid
    return p.tenant_id  # type: ignore[return-value]


async def _active_owner_count(conn: AsyncSession, tenant_id: str) -> int:
    q = sa.select(sa.func.count()).select_from(t.memberships).where(
        t.memberships.c.tenant_id == tenant_id,
        t.memberships.c.role == "owner",
        t.memberships.c.status == "active",
    )
    return (await conn.execute(q)).scalar_one()


class CreateUser(BaseModel):
    email: EmailStr
    name: str
    role: str                       # admin | member (owner is set at tenant creation)
    password: str | None = None     # required only for a brand-new identity
    tenant_id: str | None = None    # staff only


class PatchUser(BaseModel):
    name: str | None = None
    role: str | None = None
    status: str | None = None       # active | disabled


class PasswordChange(BaseModel):
    new_password: str
    current_password: str | None = None  # required for self-change


@router.get("")
async def list_users(
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if p.tenant_id is None:
        # Staff or no active tenant: cross-tenant listing lives at /admin/v1/users.
        raise api_error(400, "validation_error", "No active workspace selected")
    q = (
        sa.select(
            t.users.c.id, t.users.c.email, t.users.c.name,
            t.memberships.c.role, t.memberships.c.status, t.users.c.must_change_password,
        )
        .select_from(t.memberships.join(t.users, t.memberships.c.user_id == t.users.c.id))
        .where(
            t.memberships.c.tenant_id == p.tenant_id,
            t.memberships.c.status == "active",
        )
    )
    rows = (await conn.execute(q)).mappings().all()
    return {"users": [dict(r) for r in rows]}


@router.post("", status_code=201)
async def create_user(
    body: CreateUser,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tenant_id = _tenant_scope(p, body.tenant_id)
    if body.role not in ("admin", "member"):
        raise api_error(400, "validation_error",
                        "role must be 'admin' or 'member'", "role")

    existing = (
        await conn.execute(
            sa.select(t.users.c.id, t.users.c.is_staff)
            .where(t.users.c.email == str(body.email).lower())
        )
    ).mappings().first()

    if existing is None:
        if not body.password:
            raise api_error(400, "validation_error",
                            "password is required for a new user", "password")
        user_row = new_user_row(
            email=str(body.email), name=body.name, password=body.password,
        )
        try:
            await conn.execute(sa.insert(t.users).values(**user_row))
        except sa.exc.IntegrityError as exc:
            raise api_error(409, "validation_error", "Email already in use", "email") from exc
        user_id = user_row["id"]
        created_identity = True
    else:
        if existing["is_staff"]:
            raise api_error(409, "validation_error",
                            "That email belongs to a staff account", "email")
        user_id = existing["id"]
        created_identity = False

    try:
        await conn.execute(
            sa.insert(t.memberships).values(
                **new_membership_row(user_id=user_id, tenant_id=tenant_id, role=body.role)
            )
        )
    except sa.exc.IntegrityError as exc:
        raise api_error(409, "validation_error",
                        "Already a member of this workspace", "email") from exc

    actor_type = actor_type_for(p)
    await audit(
        conn, actor_type=actor_type, actor_id=p.user_id, action="user.create" if created_identity else "membership.add",
        target_type="user", target_id=user_id,
        details={"email": str(body.email).lower(), "role": body.role, "tenant_id": tenant_id},
    )
    await conn.commit()
    return {
        "id": user_id, "email": str(body.email).lower(), "role": body.role,
        "must_change_password": created_identity,
    }


@router.patch("/{uid}")
async def patch_user(
    uid: str,
    body: PatchUser,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "No active workspace selected")
    membership = (
        await conn.execute(
            sa.select(t.memberships).where(
                t.memberships.c.user_id == uid,
                t.memberships.c.tenant_id == p.tenant_id,
            )
        )
    ).mappings().first()
    if membership is None:
        raise api_error(404, "not_found", "User not found")
    owners = await _active_owner_count(conn, p.tenant_id)

    # Validate everything BEFORE mutating anything.
    values: dict = {}  # type: ignore[type-arg]  # membership column changes
    audit_actions: list[str] = []
    if body.role is not None:
        if body.role not in ("owner", "admin", "member"):
            raise api_error(400, "validation_error", "Invalid role", "role")
        try:
            assert_role_change_allowed(dict(membership), new_role=body.role,
                                       active_owner_count=owners)
        except OwnerProtected as e:
            raise api_error(409, "validation_error", str(e), "role") from e
        values["role"] = body.role
        audit_actions.append("membership.role_change")
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise api_error(400, "validation_error", "Invalid status", "status")
        if body.status == "disabled":
            try:
                assert_can_disable_or_delete(dict(membership), active_owner_count=owners)
            except OwnerProtected as e:
                raise api_error(409, "validation_error", str(e), "status") from e
            audit_actions.append("membership.disable")
        else:
            audit_actions.append("membership.enable")
        values["status"] = body.status

    # Apply writes after validation passed.
    response: dict = {"id": uid}  # type: ignore[type-arg]
    audit_details: dict = dict(values)  # type: ignore[type-arg]

    if body.name is not None:
        await conn.execute(
            sa.update(t.users).where(t.users.c.id == uid)
            .values(name=body.name, updated_at=datetime.now(UTC))
        )
        audit_actions.append("user.rename")
        audit_details["name"] = body.name
        response["name"] = body.name

    if values:
        values["updated_at"] = datetime.now(UTC)
        try:
            await conn.execute(
                sa.update(t.memberships)
                .where(t.memberships.c.user_id == uid, t.memberships.c.tenant_id == p.tenant_id)
                .values(**values)
            )
        except sa.exc.IntegrityError as exc:
            raise api_error(409, "validation_error",
                            owner_conflict_message(str(getattr(exc, "orig", exc))),
                            "role") from exc
        if values.get("status") == "disabled":
            await conn.execute(
                sa.update(t.sessions)
                .where(
                    t.sessions.c.user_id == uid,
                    t.sessions.c.active_tenant_id == p.tenant_id,
                    t.sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
        response.update({k: v for k, v in values.items() if k != "updated_at"})

    if audit_actions:
        actor_type = actor_type_for(p)
        for action in audit_actions:
            await audit(conn, actor_type=actor_type, actor_id=p.user_id, action=action,
                        target_type="user", target_id=uid, details=audit_details)
        await conn.commit()
    return response


@router.post("/{uid}/password")
async def change_password(
    uid: str,
    body: PasswordChange,
    request: Request,
    p: Principal = Depends(resolve_principal),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    target = (
        await conn.execute(sa.select(t.users).where(t.users.c.id == uid))
    ).mappings().first()
    if not target:
        raise api_error(404, "not_found", "User not found")
    is_self = p.user_id == uid
    is_tenant_member = False
    if p.tenant_id is not None:
        is_tenant_member = (
            await conn.execute(
                sa.select(t.memberships.c.id).where(
                    t.memberships.c.user_id == uid,
                    t.memberships.c.tenant_id == p.tenant_id,
                    t.memberships.c.status == "active",
                )
            )
        ).first() is not None
    is_admin = p.is_staff or (
        p.user_id is not None
        and p.role in ("admin", "owner")
        and is_tenant_member
    )
    if not (is_self or is_admin):
        raise api_error(403, "forbidden", "Cannot change this user's password")
    if is_self and not is_admin:
        if not body.current_password or not verify_password(
            body.current_password, target["password_hash"]
        ):
            raise api_error(400, "validation_error", "Current password is incorrect",
                            "current_password")
    must_change = not is_self  # admin reset re-forces a change
    await conn.execute(
        sa.update(t.users).where(t.users.c.id == uid).values(
            password_hash=hash_password(body.new_password),
            must_change_password=must_change,
            updated_at=datetime.now(UTC),
        )
    )
    # Changing a password revokes the user's OTHER sessions (spec §4.3). On a
    # self-change we keep the caller's CURRENT session so a forced first-login
    # password change doesn't immediately log the user back out. An admin reset of
    # someone else's password still revokes all of that user's sessions.
    revoke = sa.update(t.sessions).where(
        t.sessions.c.user_id == uid,
        t.sessions.c.revoked_at.is_(None),
    )
    if is_self:
        current_token = request.cookies.get(SESSION_COOKIE)
        if current_token:
            revoke = revoke.where(t.sessions.c.token_hash != hash_token(current_token))
    await conn.execute(revoke.values(revoked_at=datetime.now(UTC)))
    actor_type = actor_type_for(p)
    await audit(
        conn,
        actor_type=actor_type,
        actor_id=p.user_id,
        action="user.password_reset",
        target_type="user",
        target_id=uid,
        details={"self_change": is_self},
    )
    await conn.commit()
    return {"id": uid, "must_change_password": must_change}


@router.delete("/{uid}")
async def delete_user(
    uid: str,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "No active workspace selected")
    membership = (
        await conn.execute(
            sa.select(t.memberships).where(
                t.memberships.c.user_id == uid,
                t.memberships.c.tenant_id == p.tenant_id,
            )
        )
    ).mappings().first()
    if membership is None:
        raise api_error(404, "not_found", "User not found")
    owners = await _active_owner_count(conn, p.tenant_id)
    try:
        assert_can_disable_or_delete(dict(membership), active_owner_count=owners)
    except OwnerProtected as e:
        raise api_error(409, "validation_error", str(e)) from e

    await conn.execute(
        sa.update(t.memberships)
        .where(t.memberships.c.user_id == uid, t.memberships.c.tenant_id == p.tenant_id)
        .values(status="disabled", updated_at=datetime.now(UTC))
    )
    await conn.execute(
        sa.update(t.sessions)
        .where(
            t.sessions.c.user_id == uid,
            t.sessions.c.active_tenant_id == p.tenant_id,
            t.sessions.c.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    actor_type = actor_type_for(p)
    await audit(
        conn, actor_type=actor_type, actor_id=p.user_id, action="membership.disable",
        target_type="user", target_id=uid, details={"reason": "removed", "tenant_id": p.tenant_id},
    )
    await conn.commit()
    return {"id": uid, "status": "disabled"}
