from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, EmailStr, Field
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

router = APIRouter(prefix="/admin/v1", tags=["Admin"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class OwnerSpec(BaseModel):
    email: Annotated[EmailStr, Field(description="Email address for the new tenant owner user.")]
    name: Annotated[str, Field(description="Display name for the new tenant owner user.")]
    password: Annotated[
        str,
        Field(
            description=(
                "Initial password for the owner. The owner is flagged "
                "`must_change_password` and prompted to change it on first login."
            )
        ),
    ]


class CreateTenant(BaseModel):
    name: Annotated[str, Field(description="Human-readable tenant name.")]
    limits: Annotated[
        dict | None,  # type: ignore[type-arg]
        Field(description="Optional resource-limit overrides; defaults are applied when omitted."),
    ] = None
    owner: Annotated[
        OwnerSpec | None,
        Field(
            description=(
                "Optional owner to create. When provided, a new owner user is created; "
                "when omitted, the calling staff user becomes the tenant owner."
            )
        ),
    ] = None


class PatchTenant(BaseModel):
    name: Annotated[str | None, Field(description="New tenant name, if changing.")] = None
    limits: Annotated[
        dict | None,  # type: ignore[type-arg]
        Field(
            description=(
                "Partial limit overrides; merged into existing limits (keys are not dropped)."
            )
        ),
    ] = None
    status: Annotated[
        str | None,
        Field(description="New tenant status: `active` or `disabled`."),
    ] = None


class CreateStaff(BaseModel):
    email: Annotated[EmailStr, Field(description="Email address for the new staff user.")]
    name: Annotated[str, Field(description="Display name for the new staff user.")]
    password: Annotated[
        str,
        Field(
            description=(
                "Initial password. The staff user is flagged `must_change_password` "
                "and prompted to change it on first login."
            )
        ),
    ]


class PatchStaff(BaseModel):
    status: Annotated[
        str,
        Field(description="New staff status: `active` or `disabled`."),
    ]  # active | disabled


class TenantList(BaseModel):
    """Wrapper for the list-tenants response."""

    tenants: Annotated[
        list[dict],  # type: ignore[type-arg]
        Field(
            description=(
                "All tenants with their full stored rows (id, name, limits, status, timestamps)."
            )
        ),
    ]


class CreateTenantResult(BaseModel):
    """Result of creating a tenant."""

    id: Annotated[str, Field(description="Id of the newly created tenant (`ten_` prefix).")]
    name: Annotated[str, Field(description="Name of the created tenant.")]
    owner_id: Annotated[str, Field(description="User id of the tenant owner (`usr_` prefix).")]


class DisableResult(BaseModel):
    """Result of disabling a tenant (soft delete)."""

    id: Annotated[str, Field(description="Id of the disabled tenant.")]
    status: Annotated[str, Field(description="Always `disabled` on success.")]


class UserView(BaseModel):
    """A tenant membership joined with its user."""

    id: Annotated[str, Field(description="User id (`usr_` prefix).")]
    tenant_id: Annotated[str, Field(description="Tenant the membership belongs to.")]
    email: Annotated[str, Field(description="User email address.")]
    name: Annotated[str, Field(description="User display name.")]
    role: Annotated[
        str, Field(description="Membership role within the tenant (e.g. owner, admin, member).")
    ]
    is_staff: Annotated[bool, Field(description="Whether the user is a platform staff/admin.")]
    status: Annotated[str, Field(description="Membership status (e.g. active, disabled).")]


class UserList(BaseModel):
    """Wrapper for the list-users response."""

    users: Annotated[
        list[UserView],
        Field(description="Users across tenants, optionally filtered by `tenant_id`."),
    ]


class StaffView(BaseModel):
    """A platform staff (admin) user."""

    id: Annotated[str, Field(description="Staff user id (`usr_` prefix).")]
    email: Annotated[str, Field(description="Staff email address.")]
    name: Annotated[str, Field(description="Staff display name.")]
    status: Annotated[str, Field(description="Staff status: `active` or `disabled`.")]
    must_change_password: Annotated[
        bool,
        Field(description="Whether the staff user must change their password at next login."),
    ]
    created_at: Annotated[datetime, Field(description="When the staff user was created (UTC).")]


class StaffList(BaseModel):
    """Wrapper for the list-staff response."""

    staff: Annotated[
        list[StaffView],
        Field(description="All platform staff (admin) users."),
    ]


class CreateStaffResult(BaseModel):
    """Result of creating a staff user."""

    id: Annotated[str, Field(description="Id of the newly created staff user (`usr_` prefix).")]
    is_staff: Annotated[bool, Field(description="Always `true` for a newly created staff user.")]


class StaffStatusResult(BaseModel):
    """Result of changing a staff user's status."""

    id: Annotated[str, Field(description="Id of the staff user whose status changed.")]
    status: Annotated[
        str, Field(description="The staff user's new status: `active` or `disabled`.")
    ]


class AdminHealth(BaseModel):
    """Platform health snapshot for staff dashboards."""

    status: Annotated[str, Field(description="Always `ok` when the query succeeds.")]
    tenants: Annotated[int, Field(description="Total number of tenants.")]
    running_containers: Annotated[
        int, Field(description="Count of containers currently `running`.")
    ]
    active_tasks: Annotated[
        int, Field(description="Count of tasks in `pending` or `running` state.")
    ]


@router.get("/tenants", response_model=TenantList, response_description="All tenants.")
async def list_tenants(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List all tenants on the platform.

    Staff-only (`require_staff`): rejects any non-staff caller. Returns the full
    stored row for every tenant.

    Errors: 403 `forbidden` if the caller is not staff.
    """
    rows = (await conn.execute(sa.select(t.tenants))).mappings().all()
    return {"tenants": [dict(r) for r in rows]}


@router.post(
    "/tenants",
    status_code=201,
    response_model=CreateTenantResult,
    response_description="The created tenant's id, name, and owner id.",
)
async def create_tenant(
    body: CreateTenant,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Create a tenant, either with a new owner or with the staff caller as owner.

    Staff-only (`require_staff`). Two paths:
    - When `owner` is provided, a new owner user is created (flagged
      `must_change_password`), the tenant is created, and an owner membership is
      added. Writes `tenant.create` and `user.create` audit entries.
    - When `owner` is omitted, the calling staff user becomes the tenant owner.
      Writes `tenant.create` and `membership.add` audit entries.

    Errors: 400 `validation_error` if `owner` is omitted but the credential has
    no user id (non-session admin); 409 `validation_error` if the owner email is
    already in use; 403 `forbidden` if the caller is not staff.
    """
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


@router.patch(
    "/tenants/{tid}",
    response_description=(
        "The tenant id plus only the fields that were changed (`name`, `limits`, "
        "and/or `status`)."
    ),
)
async def patch_tenant(
    tid: Annotated[str, Path(description="Id of the tenant to update (`ten_` prefix).")],
    body: PatchTenant,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Update a tenant's name, limits, and/or status.

    Staff-only (`require_staff`). Only the fields present in the body are
    changed; `limits` is merged into existing limits so a partial update never
    drops keys. Changing limits writes a `tenant.update_limits` audit entry.
    The response echoes the tenant id plus only the fields that were updated.

    Errors: 404 `not_found` if the tenant does not exist; 400 `validation_error`
    if `status` is not `active`/`disabled`; 403 `forbidden` if not staff.
    """
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


@router.delete(
    "/tenants/{tid}",
    response_model=DisableResult,
    response_description="The tenant id and its new `disabled` status.",
)
async def delete_tenant(
    tid: Annotated[str, Path(description="Id of the tenant to disable (`ten_` prefix).")],
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Disable a tenant (soft delete).

    Staff-only (`require_staff`). Sets the tenant's status to `disabled` rather
    than deleting the row, and writes a `tenant.disable` audit entry.

    Errors: 404 `not_found` if the tenant does not exist; 403 `forbidden` if the
    caller is not staff.
    """
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


@router.get("/users", response_model=UserList, response_description="Tenant users (memberships).")
async def list_all_users(
    tenant_id: Annotated[
        str | None,
        Query(description="Optional tenant id to filter the results to a single tenant."),
    ] = None,
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List tenant users (memberships joined with users), across all tenants.

    Staff-only (`require_staff`). Returns one row per membership. Pass
    `tenant_id` to restrict results to a single tenant. Staff users have no
    tenant membership and therefore do not appear here (see `/admin/v1/staff`).

    Errors: 403 `forbidden` if the caller is not staff.
    """
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


@router.get("/staff", response_model=StaffList, response_description="Platform staff users.")
async def list_staff(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List staff (admin) users.

    Staff-only (`require_staff`). Staff have no tenant membership, so the
    membership-joined `/admin/v1/users` list does not include them; use this
    endpoint to enumerate platform administrators. Ordered by creation time.

    Errors: 403 `forbidden` if the caller is not staff.
    """
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


@router.post(
    "/staff",
    status_code=201,
    response_model=CreateStaffResult,
    response_description="The new staff user's id and staff flag.",
)
async def create_staff(
    body: CreateStaff,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Create a platform staff (admin) user.

    Staff-only (`require_staff`). Creates an active staff user flagged
    `must_change_password` and writes a `user.create` audit entry.

    Errors: 409 `validation_error` if the email is already in use; 403
    `forbidden` if the caller is not staff.
    """
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


@router.patch(
    "/staff/{uid}",
    response_model=StaffStatusResult,
    response_description="The staff user's id and new status.",
)
async def set_staff_status(
    uid: Annotated[str, Path(description="Id of the staff user to update (`usr_` prefix).")],
    body: PatchStaff,
    p: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Activate or deactivate a staff user.

    Staff-only (`require_staff`). Disabling a staff user also revokes all of
    their active sessions. A staff user cannot change their own status (no
    self-lockout). Writes a `staff.status` audit entry.

    Errors: 400 `validation_error` if `status` is not `active`/`disabled`, or if
    the caller targets their own id; 404 `not_found` if the target user does not
    exist or is not a staff user; 403 `forbidden` if the caller is not staff.
    """
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


@router.get(
    "/health",
    response_model=AdminHealth,
    response_description="Platform counts: tenants, running containers, active tasks.",
)
async def health(
    _: Principal = Depends(require_staff),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Return a staff platform-health snapshot.

    Staff-only (`require_staff`). Aggregates total tenants, currently running
    containers, and active (`pending`/`running`) tasks for admin dashboards.
    Distinct from the public unauthenticated `/healthz` liveness probe.

    Errors: 403 `forbidden` if the caller is not staff.
    """
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
