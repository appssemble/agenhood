from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_KEY = b"A" * 32


async def _factory(db_url: str):
    from control_plane.db import make_engine, make_session_factory

    class _S:  # minimal Settings-like object for make_engine
        database_url = db_url

    engine = make_engine(_S())  # type: ignore[arg-type]
    return engine, make_session_factory(engine)


async def _seed_tenant(factory, tenant_id: str) -> None:
    import sqlalchemy as sa

    from control_plane.models_db import tenants

    async with factory() as s:
        await s.execute(
            sa.insert(tenants).values(
                id=tenant_id, name="t", limits={}, status="active",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_create_and_get_connection(migrated_db: str) -> None:
    from control_plane.oauth_service import create_connection, get_connection

    engine, factory = await _factory(migrated_db)
    tenant_id = "ten_svc_test"
    try:
        await _seed_tenant(factory, tenant_id)
        async with factory() as s:
            cid = await create_connection(
                s,
                tenant_id=tenant_id,
                provider="openai",
                device_code="dev-xyz",
                expires_in=900,
                master_key=_KEY,
            )
            await s.commit()
        async with factory() as s:
            row = await get_connection(s, cid)
        assert row is not None
        assert row["status"] == "pending"
        assert row["tenant_id"] == tenant_id
        # device code is encrypted, not stored in plaintext
        assert b"dev-xyz" not in row["device_code_ciphertext"]
        assert row["expires_at"] > datetime.now(UTC) + timedelta(seconds=800)
    finally:
        await engine.dispose()
