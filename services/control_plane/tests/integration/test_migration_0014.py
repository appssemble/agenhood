"""Integration test: migration 0014 drops idx_membership_owner_once, keeps one_owner."""
from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]


@pytest.mark.asyncio
async def test_owner_once_dropped_one_owner_kept(migrated_db: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_db)
    try:
        async with engine.connect() as conn:
            idx = {
                r[0] for r in await conn.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE tablename='memberships'"))
            }
            assert "idx_membership_owner_once" not in idx
            assert "idx_membership_one_owner" in idx
    finally:
        await engine.dispose()
