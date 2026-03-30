from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.bindings_service import build_binding_row
from connectors.deps import db_session as _session
from connectors.tables import container_bindings

router = APIRouter(prefix="/v1/bindings", tags=["bindings"])


class BindingIn(BaseModel):
    connection_id: str
    container_id: str
    tenant_id: str
    enabled: bool = True
    resource_filters: dict[str, Any] = Field(default_factory=dict)


@router.put("")
async def put_binding(body: BindingIn, session: AsyncSession = Depends(_session)) -> dict:  # type: ignore[type-arg]
    existing = (
        await session.execute(
            sa.select(container_bindings).where(
                container_bindings.c.connection_id == body.connection_id,
                container_bindings.c.container_id == body.container_id,
            )
        )
    ).mappings().first()
    if existing:
        await session.execute(
            sa.update(container_bindings)
            .where(container_bindings.c.id == existing["id"])
            .values(enabled=body.enabled, resource_filters=body.resource_filters)
        )
        bid = existing["id"]
    else:
        row = build_binding_row(
            connection_id=body.connection_id, container_id=body.container_id,
            tenant_id=body.tenant_id, enabled=body.enabled,
            resource_filters=body.resource_filters,
        )
        await session.execute(sa.insert(container_bindings).values(**row))
        bid = row["id"]
    await session.commit()
    return {"id": bid}


@router.get("")
async def list_bindings(
    container_id: str, session: AsyncSession = Depends(_session)
) -> dict:  # type: ignore[type-arg]
    rows = (
        await session.execute(
            sa.select(container_bindings).where(
                container_bindings.c.container_id == container_id
            )
        )
    ).mappings().all()
    return {"bindings": [dict(r) for r in rows]}
