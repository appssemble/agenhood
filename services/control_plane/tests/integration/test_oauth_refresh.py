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


async def _factory(db_url: str):
    from control_plane.db import make_engine, make_session_factory

    class _S:
        database_url = db_url

    engine = make_engine(_S())  # type: ignore[arg-type]
    return engine, make_session_factory(engine)


async def _seed_tenant_and_oauth_cred(factory, expires_at: datetime) -> str:
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    import control_plane.tables as t
    from control_plane.credentials_service import build_oauth_credential_row
    from control_plane.models_db import tenants

    async with factory() as s:
        await s.execute(
            pg_insert(tenants)
            .values(
                id="ten_seed", name="t", limits={}, status="active",
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # Remove any existing oauth_subscription credential so we get a clean slate.
        await s.execute(
            sa.delete(t.credentials).where(
                t.credentials.c.tenant_id == "ten_seed",
                t.credentials.c.provider == "openai",
                t.credentials.c.auth_method == "oauth_subscription",
            )
        )
        row = build_oauth_credential_row(
            tenant_id="ten_seed", provider="openai",
            access_token="acc-old", refresh_token="ref-old",
            token_expires_at=expires_at, account_id="acct_1",
            created_by=None, master_key=_KEY,
        )
        await s.execute(sa.insert(t.credentials).values(**row))
        await s.commit()
        return row["id"]


@respx.mock
@pytest.mark.asyncio
async def test_ensure_fresh_refreshes_when_within_grace(migrated_db: str) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.oauth_service import ensure_fresh_oauth

    s = Settings.from_env()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(
            200, json={"access_token": "acc-new", "refresh_token": "ref-new", "expires_in": 3600}
        )
    )
    engine, factory = await _factory(migrated_db)
    try:
        now = datetime.now(UTC)
        cred_id = await _seed_tenant_and_oauth_cred(factory, expires_at=now + timedelta(seconds=60))
        async with factory() as sess:
            row = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
            fresh = await ensure_fresh_oauth(
                sess, dict(row), settings=s, master_key=_KEY, now=now
            )
            await sess.commit()
        assert fresh["access_token"] == "acc-new"
        # persisted
        async with factory() as sess:
            from control_plane.credentials_service import decrypt_oauth_row
            row2 = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
            assert decrypt_oauth_row(dict(row2), _KEY)["access_token"] == "acc-new"
    finally:
        await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_ensure_fresh_no_refresh_when_far_from_expiry(migrated_db: str) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.oauth_service import ensure_fresh_oauth

    s = Settings.from_env()
    refresh_route = respx.post(s.openai_oauth_refresh_url)
    engine, factory = await _factory(migrated_db)
    try:
        now = datetime.now(UTC)
        cred_id = await _seed_tenant_and_oauth_cred(factory, expires_at=now + timedelta(hours=2))
        async with factory() as sess:
            row = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
            fresh = await ensure_fresh_oauth(sess, dict(row), settings=s, master_key=_KEY, now=now)
        assert fresh["access_token"] == "acc-old"
        assert not refresh_route.called
    finally:
        await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_ensure_fresh_invalid_grant_sets_reauth_required(migrated_db: str) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.oauth_service import OAuthReauthRequired, ensure_fresh_oauth

    s = Settings.from_env()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    engine, factory = await _factory(migrated_db)
    try:
        now = datetime.now(UTC)
        cred_id = await _seed_tenant_and_oauth_cred(factory, expires_at=now + timedelta(seconds=30))
        async with factory() as sess:
            row = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
            with pytest.raises(OAuthReauthRequired):
                await ensure_fresh_oauth(sess, dict(row), settings=s, master_key=_KEY, now=now)
            await sess.commit()
        async with factory() as sess:
            row2 = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
        assert row2["status"] == "reauth_required"
    finally:
        await engine.dispose()


async def _seed_transient_tenant_and_oauth_cred(factory, expires_at: datetime) -> str:
    """Variant of _seed_tenant_and_oauth_cred that uses a unique tenant id for isolation."""
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    import control_plane.tables as t
    from control_plane.credentials_service import build_oauth_credential_row
    from control_plane.models_db import tenants

    tenant_id = "ten_refresh_transient"
    async with factory() as s:
        await s.execute(
            pg_insert(tenants)
            .values(
                id=tenant_id, name="t-transient", limits={}, status="active",
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # Remove any existing oauth_subscription credential so we get a clean slate.
        await s.execute(
            sa.delete(t.credentials).where(
                t.credentials.c.tenant_id == tenant_id,
                t.credentials.c.provider == "openai",
                t.credentials.c.auth_method == "oauth_subscription",
            )
        )
        row = build_oauth_credential_row(
            tenant_id=tenant_id, provider="openai",
            access_token="acc-old", refresh_token="ref-old",
            token_expires_at=expires_at, account_id="acct_1",
            created_by=None, master_key=_KEY,
        )
        await s.execute(sa.insert(t.credentials).values(**row))
        await s.commit()
        return row["id"]


@respx.mock
@pytest.mark.asyncio
async def test_transient_5xx_refresh_does_not_set_reauth_required(migrated_db: str) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.oauth_service import OAuthReauthRequired, ensure_fresh_oauth

    s = Settings.from_env()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(503)
    )
    engine, factory = await _factory(migrated_db)
    try:
        now = datetime.now(UTC)
        cred_id = await _seed_transient_tenant_and_oauth_cred(
            factory, expires_at=now + timedelta(seconds=30)
        )
        async with factory() as sess:
            row = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
            with pytest.raises(OAuthReauthRequired):
                await ensure_fresh_oauth(sess, dict(row), settings=s, master_key=_KEY, now=now)
            await sess.commit()
        async with factory() as sess:
            row2 = (
                await sess.execute(sa.select(t.credentials).where(t.credentials.c.id == cred_id))
            ).mappings().first()
        assert row2["status"] == "active", f"expected active, got {row2['status']!r}"
    finally:
        await engine.dispose()
