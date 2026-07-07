from __future__ import annotations

from collections.abc import AsyncIterator

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.audit import audit
from control_plane.auth.principal import Principal, actor_type_for, resolve_principal
from control_plane.errors import api_error
from control_plane.tenant_service import create_tenant_owned_by

router = APIRouter(prefix="/v1/tenants", tags=["Tenants"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class CreateWorkspace(BaseModel):
    name: str = Field(description="Display name for the new workspace (tenant).")


class CreateWorkspaceResponse(BaseModel):
    id: str = Field(description="Id of the newly created workspace.")
    name: str = Field(description="Display name of the workspace.")
    owner_id: str = Field(description="Id of the user who created and owns the workspace.")


@router.post(
    "",
    status_code=201,
    response_model=CreateWorkspaceResponse,
    response_description="The new workspace's id, name, and owner id.",
)
async def create_workspace(
    body: CreateWorkspace,
    request: Request,
    principal: Principal = Depends(resolve_principal),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Create a new workspace owned by the calling user.

    Requires a valid user session; the caller becomes the workspace owner. Non-staff
    users are subject to a soft per-user cap on owned workspaces
    (`max_owned_tenants_per_user`); staff are exempt. Audited as `tenant.create`
    plus a `membership.add` for the self-owner.

    Errors: 401 unauthorized when unauthenticated; 403 forbidden for an API-key
    principal (no user session) or when the owned-workspace limit is reached.
    """
    if principal.user_id is None:
        raise api_error(403, "forbidden", "Creating a workspace requires a user session")

    # Soft per-user cap (read-then-create; not DB-enforced). Adequate for a
    # low-frequency, user-initiated action.
    if not principal.is_staff:
        cap = request.app.state.settings.max_owned_tenants_per_user
        owned = (
            await conn.execute(
                sa.select(sa.func.count()).select_from(t.memberships).where(
                    t.memberships.c.user_id == principal.user_id,
                    t.memberships.c.role == "owner",
                    t.memberships.c.status == "active",
                )
            )
        ).scalar_one()
        if owned >= cap:
            raise api_error(403, "forbidden", "Workspace limit reached")

    tenant_id = await create_tenant_owned_by(conn, user_id=principal.user_id, name=body.name)
    actor_type = actor_type_for(principal)
    await audit(
        conn, actor_type=actor_type, actor_id=principal.user_id, action="tenant.create",
        target_type="tenant", target_id=tenant_id,
        details={"name": body.name, "owner_id": principal.user_id},
    )
    await audit(
        conn, actor_type=actor_type, actor_id=principal.user_id, action="membership.add",
        target_type="user", target_id=principal.user_id,
        details={"role": "owner", "tenant_id": tenant_id, "self_owner": True},
    )
    await conn.commit()
    return {"id": tenant_id, "name": body.name, "owner_id": principal.user_id}
