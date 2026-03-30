from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.deps import db_session as _session
from connectors.errors import APIError
from connectors.ids import new_id
from connectors.tables import container_bindings, routing_rules

router = APIRouter(prefix="/v1/routing-rules", tags=["routing-rules"])


class RuleIn(BaseModel):
    connection_id: str
    tenant_id: str
    priority: int = 100
    match: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    input_template: str = "{{ text }}"
    surface: list[str] = Field(default_factory=lambda: ["reasoning", "result"])
    enabled: bool = True


@router.put("")
async def put_rule(body: RuleIn, session: AsyncSession = Depends(_session)) -> dict:  # type: ignore[type-arg]
    target_cid = body.target.get("container_id")
    if target_cid:
        binding = (
            await session.execute(
                sa.select(container_bindings).where(
                    container_bindings.c.connection_id == body.connection_id,
                    container_bindings.c.container_id == target_cid,
                    container_bindings.c.enabled.is_(True),
                )
            )
        ).mappings().first()
        if not binding:
            raise APIError(
                400, "validation_error",
                f"no enabled binding for container {target_cid} on this connection",
                "target",
            )
    now = datetime.now(UTC)
    rid = new_id("rul")
    await session.execute(sa.insert(routing_rules).values(
        id=rid, connection_id=body.connection_id, tenant_id=body.tenant_id,
        priority=body.priority, match=body.match, target=body.target,
        input_template=body.input_template, surface=body.surface,
        enabled=body.enabled, created_at=now, updated_at=now,
    ))
    await session.commit()
    return {"id": rid}


@router.get("")
async def list_rules(
    connection_id: str, session: AsyncSession = Depends(_session)
) -> dict:  # type: ignore[type-arg]
    rows = (
        await session.execute(
            sa.select(routing_rules)
            .where(routing_rules.c.connection_id == connection_id)
            .order_by(routing_rules.c.priority.asc())
        )
    ).mappings().all()
    return {"routing_rules": [dict(r) for r in rows]}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, session: AsyncSession = Depends(_session)) -> dict:  # type: ignore[type-arg]
    await session.execute(sa.delete(routing_rules).where(routing_rules.c.id == rule_id))
    await session.commit()
    return {"status": "deleted"}
