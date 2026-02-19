from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.passwords import hash_password
from control_plane.auth.principal import Principal, require_staff
from control_plane.errors import api_error
from control_plane.ids_compat import new_id
from control_plane.membership_service import new_membership_row
from control_plane.tenant_defaults import persisted_limits
from control_plane.tenant_service import create_tenant_owned_by

router = APIRouter(prefix="/admin/v1", tags=["admin"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class OwnerSpec(BaseModel):
    email: EmailStr
    name: str
    password: str


class CreateTenant(BaseModel):
    name: str
    limits: dict | None = None  # type: ignore[type-arg]
    owner: OwnerSpec | None = None


class PatchTenant(BaseModel):
    name: str | None = None
    limits: dict | None = None  # type: ignore[type-arg]
    status: str | None = None


class CreateStaff(BaseModel):
    email: EmailStr
    name: str
    password: str


class PatchStaff(BaseModel):
    status: str  # active | disabled


@router.get("/tenants")
async def list_tenants(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    rows = (await conn.execute(sa.select(t.tenants))).mappings().all()
    return {"tenants": [dict(r) for r in rows]}


@router.post("/tenants", status_code=201)
async def create_tenant(
    body: CreateTenant,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if body.owner is not None:
        # Owner-provided path (e.g. bootstrap setup): create a separate owner user.
        now = datetime.now(UTC)
        tenant_id = new_id("ten")
        await conn.execute(
            sa.insert(t.tenants).values(
                id=tenant_id,
                name=body.name,
                limits=persisted_limits(body.limits),
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        owner_id = new_id("usr")
        try:
            await conn.execute(
                sa.insert(t.users).values(
                    id=owner_id,
                    email=str(body.owner.email).lower(),
                    name=body.owner.name,
                    password_hash=hash_password(body.owner.password),
                    is_staff=False,
                    must_change_password=True,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
        except sa.exc.IntegrityError as exc:
            raise api_error(
                409, "validation_error", "Owner email already in use", "owner.email"
            ) from exc
        await conn.execute(
            sa.insert(t.memberships).values(
                **new_membership_row(user_id=owner_id, tenant_id=tenant_id, role="owner")
            )
        )
        await audit(
            conn,
            actor_type="admin",
            actor_id=p.user_id,
            action="tenant.create",
            target_type="tenant",
            target_id=tenant_id,
            details={"name": body.name, "owner_id": owner_id},
        )
        await audit(
            conn,
            actor_type="admin",
            actor_id=p.user_id,
            action="user.create",
            target_type="user",
            target_id=owner_id,
            details={"role": "owner", "tenant_id": tenant_id},
        )
    else:
        # Staff-becomes-owner path: the calling staff user is the accountable owner.
        if p.user_id is None:
            raise api_error(400, "validation_error",
                            "owner is required when using a non-session admin credential", "owner")
        owner_id = p.user_id
        tenant_id = await create_tenant_owned_by(
            conn, user_id=owner_id, name=body.name, limits=body.limits
        )
        await audit(
            conn,
            actor_type="admin",
            actor_id=p.user_id,
            action="tenant.create",
            target_type="tenant",
            target_id=tenant_id,
            details={"name": body.name, "owner_id": owner_id},
        )
        await audit(
            conn,
            actor_type="admin",
            actor_id=p.user_id,
            action="membership.add",
            target_type="user",
            target_id=owner_id,
            details={"role": "owner", "tenant_id": tenant_id, "self_owner": True},
        )
    await conn.commit()
    return {"id": tenant_id, "name": body.name, "owner_id": owner_id}


@router.patch("/tenants/{tid}")
async def patch_tenant(
    tid: str,
    body: PatchTenant,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    existing = (
        await conn.execute(sa.select(t.tenants).where(t.tenants.c.id == tid))
    ).mappings().first()
    if not existing:
        raise api_error(404, "not_found", "Tenant not found")
    values: dict = {"updated_at": datetime.now(UTC)}  # type: ignore[type-arg]
    if body.name is not None:
        values["name"] = body.name
    if body.limits is not None:
        # Merge into existing so a partial update doesn't drop keys.
        values["limits"] = {**existing["limits"], **body.limits}
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise api_error(400, "validation_error", "Invalid status", "status")
        values["status"] = body.status
    await conn.execute(sa.update(t.tenants).where(t.tenants.c.id == tid).values(**values))
    if body.limits is not None:
        await audit(
            conn,
            actor_type="admin",
            actor_id=p.user_id,
            action="tenant.update_limits",
            target_type="tenant",
            target_id=tid,
            details={"limits": body.limits},
        )
    await conn.commit()
    return {"id": tid, **{k: v for k, v in values.items() if k != "updated_at"}}


@router.delete("/tenants/{tid}")
async def delete_tenant(
    tid: str,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    res = await conn.execute(
        sa.update(t.tenants).where(t.tenants.c.id == tid).values(
            status="disabled", updated_at=datetime.now(UTC)
        )
    )
    if res.rowcount == 0:  # type: ignore[attr-defined]
        raise api_error(404, "not_found", "Tenant not found")
    await audit(
        conn,
        actor_type="admin",
        actor_id=p.user_id,
        action="tenant.disable",
        target_type="tenant",
        target_id=tid,
        details={"status": "disabled"},
    )
    await conn.commit()
    return {"id": tid, "status": "disabled"}


@router.get("/users")
async def list_all_users(
    tenant_id: str | None = None,
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    q = (
        sa.select(
            t.users.c.id,
            t.memberships.c.tenant_id,
            t.users.c.email,
            t.users.c.name,
            t.memberships.c.role,
            t.users.c.is_staff,
            t.memberships.c.status,
        )
        .select_from(
            t.memberships.join(t.users, t.memberships.c.user_id == t.users.c.id)
        )
    )
    if tenant_id:
        q = q.where(t.memberships.c.tenant_id == tenant_id)
    rows = (await conn.execute(q)).mappings().all()
    return {"users": [dict(r) for r in rows]}


@router.get("/staff")
async def list_staff(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List staff (admin) users. Staff have no tenant membership, so the
    membership-joined /admin/v1/users list does not include them."""
    rows = (
        await conn.execute(
            sa.select(
                t.users.c.id,
                t.users.c.email,
                t.users.c.name,
                t.users.c.status,
                t.users.c.must_change_password,
                t.users.c.created_at,
            )
            .where(t.users.c.is_staff.is_(True))
            .order_by(t.users.c.created_at)
        )
    ).mappings().all()
    return {"staff": [dict(r) for r in rows]}


@router.post("/staff", status_code=201)
async def create_staff(
    body: CreateStaff,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    sid = new_id("usr")
    try:
        await conn.execute(
            sa.insert(t.users).values(
                id=sid,
                email=str(body.email).lower(),
                name=body.name,
                password_hash=hash_password(body.password),
                is_staff=True,
                must_change_password=True,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    except sa.exc.IntegrityError as exc:
        raise api_error(409, "validation_error", "Email already in use", "email") from exc
    await audit(
        conn,
        actor_type="admin",
        actor_id=p.user_id,
        action="user.create",
        target_type="user",
        target_id=sid,
        details={"is_staff": True},
    )
    await conn.commit()
    return {"id": sid, "is_staff": True}


@router.patch("/staff/{uid}")
async def set_staff_status(
    uid: str,
    body: PatchStaff,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Activate/deactivate a staff user. Disabling also revokes their sessions.
    A staff user cannot change their own status (no self-lockout)."""
    if body.status not in ("active", "disabled"):
        raise api_error(400, "validation_error", "Invalid status", "status")
    if uid == p.user_id:
        raise api_error(400, "validation_error", "You can't change your own status", "uid")
    row = (
        await conn.execute(sa.select(t.users.c.is_staff).where(t.users.c.id == uid))
    ).first()
    if row is None or not row[0]:
        raise api_error(404, "not_found", "Staff user not found")
    now = datetime.now(UTC)
    await conn.execute(
        sa.update(t.users).where(t.users.c.id == uid).values(status=body.status, updated_at=now)
    )
    if body.status == "disabled":
        await conn.execute(
            sa.update(t.sessions)
            .where(t.sessions.c.user_id == uid, t.sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    await audit(
        conn,
        actor_type="admin",
        actor_id=p.user_id,
        action="staff.status",
        target_type="user",
        target_id=uid,
        details={"status": body.status},
    )
    await conn.commit()
    return {"id": uid, "status": body.status}


@router.get("/health")
async def health(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    tenants_n = (
        await conn.execute(sa.select(sa.func.count()).select_from(t.tenants))
    ).scalar_one()
    running_n = (
        await conn.execute(
            sa.text("SELECT count(*) FROM containers WHERE status = 'running'")
        )
    ).scalar_one()
    pending_n = (
        await conn.execute(
            sa.text("SELECT count(*) FROM tasks WHERE status IN ('pending','running')")
        )
    ).scalar_one()
    return {
        "status": "ok",
        "tenants": tenants_n,
        "running_containers": running_n,
        "active_tasks": pending_n,
    }
