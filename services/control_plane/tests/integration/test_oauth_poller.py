from __future__ import annotations

import json
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


async def _seed_tenant(factory, tenant_id: str = "ten_seed") -> None:
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


def _jwt_account(acct: str) -> str:
    import base64
    import json

    def seg(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{seg({'alg':'none'})}.{seg({'chatgpt_account_id': acct})}.s"


@respx.mock
@pytest.mark.asyncio
async def test_poller_promotes_pending_to_credential(migrated_db: str) -> None:
    from control_plane.config import Settings
    from control_plane.oauth_events import OAuthEventBus
    from control_plane.oauth_service import create_connection, get_connection, oauth_poll_sweep

    s = Settings.from_env()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_code": "ac_1",
                "code_verifier": "cv_1",
                "status": "authorized",
            },
        )
    )
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc-1",
                "refresh_token": "ref-1",
                "id_token": _jwt_account("acct_42"),
                "expires_in": 3600,
            },
        )
    )

    tid = "ten_poll_promote"
    engine, factory = await _factory(migrated_db)
    try:
        await _seed_tenant(factory, tid)
        async with factory() as sess:
            cid = await create_connection(
                sess, tenant_id=tid, provider="openai",
                device_code=json.dumps({"device_auth_id": "da_1", "user_code": "UC-1"}),
                expires_in=900, master_key=_KEY,
            )
            await sess.commit()

        bus = OAuthEventBus()
        async with factory() as db:
            await oauth_poll_sweep(db, None, None, settings=s, master_key=_KEY, event_bus=bus)

        async with factory() as sess:
            conn_row = await get_connection(sess, cid)
            import sqlalchemy as sa

            import control_plane.tables as t

            cred = (
                await sess.execute(
                    sa.select(t.credentials).where(
                        t.credentials.c.tenant_id == tid,
                        t.credentials.c.auth_method == "oauth_subscription",
                    )
                )
            ).mappings().first()
        assert conn_row["status"] == "connected"
        assert conn_row["credential_id"] is not None
        assert cred is not None
        assert cred["oauth_metadata"]["account_id"] == "acct_42"
    finally:
        await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_poller_marks_pending_connection_timed_out(migrated_db: str) -> None:
    from control_plane.config import Settings
    from control_plane.oauth_events import OAuthEventBus
    from control_plane.oauth_service import create_connection, get_connection, oauth_poll_sweep

    s = Settings.from_env()
    tid = "ten_poll_timeout"
    engine, factory = await _factory(migrated_db)
    try:
        await _seed_tenant(factory, tid)
        async with factory() as sess:
            cid = await create_connection(
                sess, tenant_id=tid, provider="openai",
                device_code="dev-2", expires_in=900, master_key=_KEY,
            )
            # Force it already-expired.
            import sqlalchemy as sa

            import control_plane.tables as t

            await sess.execute(
                sa.update(t.oauth_connections)
                .where(t.oauth_connections.c.id == cid)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await sess.commit()

        async with factory() as db:
            await oauth_poll_sweep(
                db, None, None, settings=s, master_key=_KEY, event_bus=OAuthEventBus()
            )

        async with factory() as sess:
            row = await get_connection(sess, cid)
        assert row["status"] == "timeout"
    finally:
        await engine.dispose()
