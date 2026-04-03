from __future__ import annotations

import asyncio
import base64
import os

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.app import create_app
from connectors.connections_service import build_connection_row
from connectors.tables import connections, metadata

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


def _strip_helpers(row: dict) -> dict:  # type: ignore[type-arg]
    return {k: v for k, v in row.items() if not k.startswith("_")}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(KEY).decode())

    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # Use asyncio.run() in this sync fixture — safe because no event loop is
    # running at fixture setup time (sync fixtures run outside the event loop
    # even under asyncio_mode=auto).
    async def _setup() -> None:
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)

        row = build_connection_row(
            tenant_id="ten_1",
            provider="slack",
            external_id="T123",
            display_name="Acme Slack",
            access_token="xoxb-abc1234",
            refresh_token=None,
            token_expires_at=None,
            cp_api_key=None,
            scopes="chat:write",
            metadata={},
            master_key=KEY,
        )
        async with eng.begin() as conn:
            await conn.execute(sa.insert(connections).values(**_strip_helpers(row)))

        await eng.dispose()

    asyncio.run(_setup())

    # Wire up a fresh engine (same file) to the app so the route can read the
    # seeded row.
    app = create_app(start_background=False)
    eng = create_async_engine(db_url)
    app.state.engine = eng
    app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)

    return TestClient(app)


def test_list_connections_returns_public_view(client: TestClient) -> None:
    r = client.get("/v1/connections", params={"tenant_id": "ten_1"})
    assert r.status_code == 200
    data = r.json()
    assert "connections" in data
    conns = data["connections"]
    assert len(conns) == 1
    c = conns[0]
    assert c["provider"] == "slack"
    assert "access_token_ciphertext" not in c
    assert "cp_api_key_ciphertext" not in c
