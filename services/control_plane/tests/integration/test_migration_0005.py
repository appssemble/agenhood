"""Integration test: migration 0005 — unique semantic assertions only.

Column/table existence is now covered by the upgrade-clean gate and the drift
equality guard.  What remains here is migration *semantics* not captured by
either: a nullability flip and an index rename.
"""
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
async def test_credentials_nullable_flip_and_index_rename(migrated_db: str) -> None:
    """key_ciphertext / key_last4 must be nullable at head (oauth rows omit them),
    and the 2-col index must have been replaced by the 3-col method index."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_db)
    try:
        async with engine.connect() as conn:
            # key_ciphertext / key_last4 must now be nullable (oauth rows omit them).
            nullable = {
                r[0]: r[1]
                for r in await conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name='credentials'"
                    )
                )
            }
            assert nullable["key_ciphertext"] == "YES"
            assert nullable["key_last4"] == "YES"

            cred_idx = {
                r[0]
                for r in await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename='credentials'")
                )
            }
            assert "idx_credentials_tenant_provider_method" in cred_idx, cred_idx
            assert "idx_credentials_tenant_provider" not in cred_idx, (
                "old 2-col unique index must be dropped"
            )
    finally:
        await engine.dispose()
