from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.connections_service import public_connection_view
from connectors.deps import db_session as _session
from connectors.tables import connections

router = APIRouter(prefix="/v1/connections", tags=["connections"])


@router.get("")
async def list_connections(
    tenant_id: str, session: AsyncSession = Depends(_session)
) -> dict:  # type: ignore[type-arg]
    rows = (
        await session.execute(
            sa.select(connections).where(connections.c.tenant_id == tenant_id)
        )
    ).mappings().all()
    return {"connections": [public_connection_view(dict(r)) for r in rows]}


@router.delete("/{connection_id}")
async def revoke_connection(
    connection_id: str, session: AsyncSession = Depends(_session)
) -> dict:  # type: ignore[type-arg]
    await session.execute(
        sa.update(connections)
        .where(connections.c.id == connection_id)
        .values(status="revoked")
    )
    await session.commit()
    return {"status": "revoked"}
