import asyncio
import base64
import os

import httpx
import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.app import create_app
from connectors.connections_service import decrypt_access_token
from connectors.tables import connections, metadata

pytestmark = pytest.mark.unit
KEY = os.urandom(32)


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(KEY).decode())
    a = create_app(start_background=False)
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"

    async def _init():
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())

    eng = create_async_engine(db_url)
    a.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
    a.state.master_key = KEY
    a.state._db_url = db_url
    return a


def test_slack_oauth_callback_creates_connection(app, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "ok": True, "access_token": "xoxb-REAL", "scope": "chat:write",
            "team": {"id": "T999", "name": "Acme"}, "bot_user_id": "U1",
        })
    from connectors.providers.slack import SlackProvider
    prov = SlackProvider(signing_secret="x", client_id="c", client_secret="s")
    prov._transport = httpx.MockTransport(handler)
    app.state.providers = {"slack": prov}

    tc = TestClient(app)
    r = tc.get("/v1/oauth/slack/callback",
               params={"code": "abc", "state": "ten_1|tk_live_z"})
    assert r.status_code in (200, 302)

    async def _check():
        eng = create_async_engine(app.state._db_url)
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with factory() as s:
            row = (await s.execute(sa.select(connections))).mappings().first()
        await eng.dispose()
        return row
    row = asyncio.run(_check())
    assert row["external_id"] == "T999"
    assert decrypt_access_token(dict(row), KEY) == "xoxb-REAL"


def test_github_callback_creates_installation_connection(app):
    app.state.providers = {}

    tc = TestClient(app)
    r = tc.get("/v1/oauth/github/callback",
               params={"installation_id": "inst_55", "state": "ten_1|tk_live_z"})
    assert r.status_code in (200, 302)

    async def _check():
        eng = create_async_engine(app.state._db_url)
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with factory() as s:
            row = (await s.execute(sa.select(connections))).mappings().first()
        await eng.dispose()
        return row
    row = asyncio.run(_check())
    assert row["external_id"] == "inst_55"
    assert row["provider"] == "github"
    assert row["access_token_ciphertext"] is None
