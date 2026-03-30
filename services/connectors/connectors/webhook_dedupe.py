from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.ids import new_id
from connectors.tables import webhook_events


async def claim_delivery(
    session: AsyncSession, provider: str, external_delivery_id: str, digest: str
) -> bool:
    """Insert a webhook_events row; return False if this delivery was already seen."""
    try:
        await session.execute(
            sa.insert(webhook_events).values(
                id=new_id("whk"), provider=provider,
                external_delivery_id=external_delivery_id, payload_digest=digest,
                received_at=datetime.now(UTC),
            )
        )
        await session.flush()
        return True
    except IntegrityError:
        await session.rollback()
        return False
