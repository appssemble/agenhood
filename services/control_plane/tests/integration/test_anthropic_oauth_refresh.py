from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_KEY = b"A" * 32


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_refresh_rotates_and_persists(migrated_db: str) -> None:
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.credentials_service import build_oauth_credential_row, decrypt_oauth_row
    from control_plane.db import make_engine, make_session_factory
    from control_plane.models_db import tenants
    from control_plane.oauth_service import ensure_fresh_oauth

    class _S:
        database_url = migrated_db
    factory = make_session_factory(make_engine(_S()))  # type: ignore[arg-type]

    now = datetime.now(UTC)
    s = Settings.from_env()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={
            "access_token": "fresh-acc", "refresh_token": "rotated-ref", "expires_in": 28800,
        })
    )
    async with factory() as db:
        await db.execute(pg_insert(tenants).values(
            id="ten_a", name="t", limits={}, status="active", created_at=now,
        ).on_conflict_do_nothing(index_elements=["id"]))
        row = build_oauth_credential_row(
            tenant_id="ten_a", provider="anthropic",
            access_token="stale-acc", refresh_token="old-ref",
            token_expires_at=now - timedelta(seconds=10),  # already expired
            account_id="acct-a", created_by=None, master_key=_KEY,
        )
        await db.execute(sa.insert(t.credentials).values(**row))
        await db.commit()
        cred_row = dict((await db.execute(
            sa.select(t.credentials).where(t.credentials.c.id == row["id"])
        )).mappings().first())

        out = await ensure_fresh_oauth(db, cred_row, settings=s, master_key=_KEY, now=now)
        assert out["access_token"] == "fresh-acc"
        assert out["refresh_token"] == "rotated-ref"

        # persisted, not just returned
        reread = dict((await db.execute(
            sa.select(t.credentials).where(t.credentials.c.id == row["id"])
        )).mappings().first())
        data = decrypt_oauth_row(reread, _KEY)
        assert data["access_token"] == "fresh-acc"
        assert data["refresh_token"] == "rotated-ref"
