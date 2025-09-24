from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.ids_compat import new_id
from control_plane.membership_service import new_membership_row
from control_plane.tenant_defaults import persisted_limits


async def create_tenant_owned_by(
    conn: AsyncSession,
    *,
    user_id: str,
    name: str,
    limits: dict | None = None,  # type: ignore[type-arg]
) -> str:
    """Create a tenant and an `owner` membership for `user_id`; return the tenant id.

    The caller is responsible for audit logging and committing the transaction.
    """
    now = datetime.now(UTC)
    tenant_id = new_id("ten")
    await conn.execute(
        sa.insert(t.tenants).values(
            id=tenant_id,
            name=name,
            limits=persisted_limits(limits),
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    await conn.execute(
        sa.insert(t.memberships).values(
            **new_membership_row(user_id=user_id, tenant_id=tenant_id, role="owner")
        )
    )
    return tenant_id
