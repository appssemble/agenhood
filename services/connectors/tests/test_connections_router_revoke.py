from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from connectors.tables import connections

pytestmark = pytest.mark.unit


def test_delete_connection_marks_revoked(client_with_conn):
    """DELETE /v1/connections/{connection_id} sets status='revoked' and returns
    {"status": "revoked"}.  The row must be marked revoked in the DB — list
    filters on tenant so we verify via a raw SQL read."""
    client, conn_id = client_with_conn
    r = client.delete(f"/v1/connections/{conn_id}")
    assert r.status_code == 200
    assert r.json() == {"status": "revoked"}

    # Verify the row's status column was actually updated.
    db_url = client.app.state._test_db_url

    async def _status() -> str:
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            row = (await conn.execute(
                sa.select(connections.c.status).where(connections.c.id == conn_id)
            )).first()
        await eng.dispose()
        return row[0]

    assert asyncio.run(_status()) == "revoked"


def test_delete_connection_unknown_id_is_noop(client_with_conn):
    """DELETE on a non-existent connection_id is a no-op: returns 200 with
    {"status": "revoked"} (the handler does not 404 — it updates 0 rows)."""
    client, _conn_id = client_with_conn
    r = client.delete("/v1/connections/conn_does_not_exist")
    assert r.status_code == 200
    assert r.json() == {"status": "revoked"}
