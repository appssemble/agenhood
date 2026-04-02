from __future__ import annotations

import asyncio
import base64
import os

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.app import create_app
from connectors.bindings_service import build_binding_row
from connectors.connections_service import build_connection_row
from connectors.tables import connections, container_bindings, metadata

# A single fixed key for all conftest-based tests.  Each test function gets
# its own tmp_path (and therefore its own DB file), so the key can be shared.
_KEY = os.urandom(32)


def _strip_helpers(row: dict) -> dict:  # type: ignore[type-arg]
    return {k: v for k, v in row.items() if not k.startswith("_")}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Return a TestClient backed by a fresh empty SQLite DB (all tables created)."""
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(_KEY).decode())

    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    async def _setup() -> None:
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await eng.dispose()

    asyncio.run(_setup())

    app = create_app(start_background=False)
    eng = create_async_engine(db_url)
    app.state.engine = eng
    app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
    # Stash for dependent fixtures that need to seed the same file.
    app.state._test_db_url = db_url
    app.state._test_key = _KEY

    return TestClient(app)


@pytest.fixture
def client_with_conn(client):  # type: ignore[type-arg]
    """Seed ONE connection + ONE enabled container_binding (cnt_1) into the
    same SQLite file the TestClient's app reads from, then yield (client, conn_id)."""
    db_url: str = client.app.state._test_db_url
    key: bytes = client.app.state._test_key

    async def _seed() -> str:
        eng = create_async_engine(db_url)
        conn_row = build_connection_row(
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
            master_key=key,
        )
        bnd_row = build_binding_row(
            connection_id=conn_row["id"],
            container_id="cnt_1",
            tenant_id="ten_1",
            enabled=True,
            resource_filters={},
        )
        async with eng.begin() as txn:
            await txn.execute(
                sa.insert(connections).values(**_strip_helpers(conn_row))
            )
            await txn.execute(sa.insert(container_bindings).values(**bnd_row))
        await eng.dispose()
        return conn_row["id"]

    conn_id = asyncio.run(_seed())
    yield client, conn_id
