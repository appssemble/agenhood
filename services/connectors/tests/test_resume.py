import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.connections_service import build_connection_row
from connectors.resume import resume_open_deliveries
from connectors.tables import connections, deliveries, metadata

pytestmark = pytest.mark.unit
KEY = os.urandom(32)


class FakeProvider:
    name = "slack"

    async def mint_token(self, row: dict, master_key: bytes) -> str:  # type: ignore[type-arg]
        return "tok"

    async def post_initial(self, token: str, origin_ref: dict, body: str) -> dict:  # type: ignore[type-arg]
        return {"channel": "C1", "ts": "1"}

    async def update_message(self, token: str, handle: dict, body: str) -> None:  # type: ignore[type-arg]
        self.body = body


class FakeCP:
    async def stream_events(  # type: ignore[override]
        self, *, container_id: str, task_id: str, api_key: str, after_seq: int = 0
    ):  # type: ignore[return]
        yield {"seq": after_seq + 1, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "RESUMED"}, "error": None}}


@pytest.mark.asyncio
async def test_resume_finishes_open_delivery() -> None:
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    conn_row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T1", display_name="A",
        access_token="xoxb-1", refresh_token=None, token_expires_at=None,
        cp_api_key="tk_live_z", scopes="", metadata={}, master_key=KEY,
    )
    insert_conn = {k: v for k, v in conn_row.items() if not k.startswith("_")}
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**insert_conn))
        await s.execute(sa.insert(deliveries).values(
            id="dlv_1", task_id="tsk_1", container_id="cnt_1",
            connection_id=conn_row["id"], origin_ref={"channel": "C1", "thread_ts": "1"},
            provider_message_handle={"channel": "C1", "ts": "1"},
            surface=["result"], last_seq=0, state="streaming",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
        await s.commit()

    await resume_open_deliveries(
        factory=factory, providers={"slack": FakeProvider()},
        cp_client=FakeCP(), master_key=KEY, coalesce_ms=0,
    )

    async with factory() as s:
        row = (await s.execute(sa.select(deliveries))).mappings().first()
    assert row["state"] == "done"
    assert row["last_seq"] == 1
