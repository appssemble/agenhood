"""Smoke test: Postgres container up, schema created, JSONB round-trip."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from connectors.ids import new_id
from connectors.tables import connections

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_up_and_jsonb_roundtrip(session_factory):
    """Prove the container is live, create_all ran, and JSONB columns work."""
    row = {
        "id": new_id("con"),
        "tenant_id": "ten_smoke",
        "provider": "slack",
        "external_id": "T_SMOKE",
        "display_name": "Smoke Workspace",
        "status": "active",
        "access_token_ciphertext": None,
        "refresh_token_ciphertext": None,
        "token_expires_at": None,
        "cp_api_key_ciphertext": None,
        "scopes": "chat:write",
        "connection_metadata": {"smoke": True, "value": 42},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    async with session_factory() as s:
        await s.execute(sa.insert(connections).values(**row))
        await s.commit()

    async with session_factory() as s:
        result = await s.execute(
            sa.select(connections.c.connection_metadata).where(
                connections.c.id == row["id"]
            )
        )
        fetched = result.scalar_one()

    assert fetched == {"smoke": True, "value": 42}, f"JSONB mismatch: {fetched!r}"
