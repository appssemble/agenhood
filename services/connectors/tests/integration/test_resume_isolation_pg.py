from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks

from connectors.connections_service import build_connection_row
from connectors.ids import new_id
from connectors.models import NormalizedEvent
from connectors.orchestrator import handle_event
from connectors.resume import resume_open_deliveries
from connectors.tables import (
    connections,
    container_bindings,
    deliveries,
    routing_rules,
)

pytestmark = pytest.mark.integration


class ResumeProvider:
    name = "slack"

    def __init__(self) -> None:
        self.body: str | None = None
        self.post_initial_calls = 0

    async def mint_token(self, row, master_key) -> str:
        return "tok"

    async def post_initial(self, token, origin_ref, body) -> dict[str, Any]:
        self.post_initial_calls += 1
        return {"channel": "C1", "ts": "1"}

    async def update_message(self, token, handle, body) -> None:
        self.body = body


class ResumeCP:
    async def stream_events(self, *, container_id, task_id, api_key, after_seq=0):
        yield {"seq": after_seq + 1, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "RESUMED-PG"},
                           "error": None}}


async def _seed_conn(factory, master_key) -> dict[str, Any]:
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T1", display_name="A",
        access_token="xoxb-1", refresh_token=None, token_expires_at=None,
        cp_api_key="tk_live_z", scopes="", metadata={}, master_key=master_key)
    insert = {k: v for k, v in conn_row.items() if not k.startswith("_")}
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**insert))
        await s.commit()
    return conn_row


@pytest.mark.asyncio
async def test_resume_finishes_streaming_delivery_on_postgres(session_factory, master_key):
    conn_row = await _seed_conn(session_factory, master_key)
    now = datetime.now(UTC)
    async with session_factory() as s:
        await s.execute(sa.insert(deliveries).values(
            id="dlv_1", task_id="tsk_1", container_id="cnt_1",
            connection_id=conn_row["id"],
            origin_ref={"channel": "C1", "thread_ts": "1"},
            provider_message_handle={"channel": "C1", "ts": "1"},
            surface=["result"], last_seq=0, state="streaming",
            created_at=now, updated_at=now))
        await s.commit()

    provider = ResumeProvider()
    await resume_open_deliveries(
        factory=session_factory, providers={"slack": provider},
        cp_client=ResumeCP(), master_key=master_key, coalesce_ms=0)

    async with session_factory() as s:
        row = (await s.execute(sa.select(deliveries))).mappings().first()
    assert row["state"] == "done" and row["last_seq"] == 1
    assert provider.body is not None and "RESUMED-PG" in provider.body  # rendering
    # Idempotency: a delivery with provider_message_handle already set must NOT
    # re-post the initial message on resume (skip-if-handle-set). Without this
    # the test would pass even if the skip condition were inverted.
    assert provider.post_initial_calls == 0
    # JSONB columns survive the asyncpg round-trip as real dicts (the PG-tier's
    # raison d'être — SQLite would store these as text).
    assert row["origin_ref"] == {"channel": "C1", "thread_ts": "1"}
    assert row["provider_message_handle"] == {"channel": "C1", "ts": "1"}


@pytest.mark.asyncio
async def test_cross_tenant_event_not_routed_on_postgres(session_factory, master_key):
    conn_row = await _seed_conn(session_factory, master_key)
    now = datetime.now(UTC)
    async with session_factory() as s:
        await s.execute(sa.insert(container_bindings).values(
            id=new_id("bnd"), connection_id=conn_row["id"], container_id="cnt_1",
            tenant_id="ten_1", enabled=True, resource_filters={},
            created_at=now, updated_at=now))
        await s.execute(sa.insert(routing_rules).values(
            id=new_id("rul"), connection_id=conn_row["id"], tenant_id="ten_1",
            priority=10, match={}, target={"container_id": "cnt_1"},
            input_template="{{ text }}", surface=["result"], enabled=True,
            created_at=now, updated_at=now))
        await s.commit()

    class ForeignProvider:
        name = "slack"

        def normalize_event(self, payload):
            return NormalizedEvent(
                provider="slack", event_type="app_mention",
                external_delivery_id="ev_foreign", resource="C1",
                thread_key="C1:ts1", text="hi",
                origin_ref={"channel": "C1", "thread_ts": "ts1"},
                external_id="T_OTHER")

        async def mint_token(self, row, master_key):
            return "tok"

        async def post_initial(self, token, origin_ref, body):
            return {"channel": "C1", "ts": "1"}

        async def update_message(self, token, handle, body):
            return None

    class CountingCP:
        def __init__(self):
            self.submits = 0

        async def submit_task(self, *, container_id, api_key, prompt, metadata):
            self.submits += 1
            return "tsk_nope"

        async def stream_events(self, *, container_id, task_id, api_key, after_seq=0):
            yield {"seq": 1, "type": "status_change",
                   "payload": {"to": "succeeded", "result": {"output": "x"},
                               "error": None}}

    cp = CountingCP()
    result = await handle_event(
        provider=ForeignProvider(), payload={"event_id": "ev_foreign"},
        factory=session_factory, cp_client=cp, master_key=master_key,
        coalesce_ms=0, background_tasks=BackgroundTasks())
    assert result == {"status": "no_route"} and cp.submits == 0
    async with session_factory() as s:
        rows = (await s.execute(sa.select(deliveries))).mappings().all()
    assert len(rows) == 0
