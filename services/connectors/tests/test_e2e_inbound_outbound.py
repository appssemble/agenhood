from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.bindings_service import build_binding_row
from connectors.connections_service import build_connection_row
from connectors.ids import new_id
from connectors.models import NormalizedEvent
from connectors.orchestrator import handle_event
from connectors.tables import (
    connections,
    container_bindings,
    deliveries,
    metadata,
    routing_rules,
    webhook_events,
)

pytestmark = pytest.mark.integration
KEY = os.urandom(32)


class FakeProvider:
    name = "slack"
    def __init__(self):
        self.updates = []
    def normalize_event(self, payload):
        ev = payload["event"]
        return NormalizedEvent(
            provider="slack", event_type="app_mention",
            external_delivery_id=payload["event_id"], resource=ev["channel"],
            thread_key=f"{ev['channel']}:{ev['ts']}", text=ev["text"],
            origin_ref={"channel": ev["channel"], "thread_ts": ev["ts"]},
            external_id=payload.get("team_id"),
        )
    async def mint_token(self, row, master_key): return "tok"
    async def post_initial(self, token, origin_ref, body):
        return {"channel": origin_ref["channel"], "ts": "msg1"}
    async def update_message(self, token, handle, body):
        self.updates.append(body)


class FakeCP:
    def __init__(self):
        self.submits = 0
    async def submit_task(self, *, container_id, api_key, prompt, metadata):
        self.submits += 1
        return "tsk_e2e"
    async def stream_events(self, *, container_id, task_id, api_key, after_seq=0):
        if after_seq < 1:
            yield {"seq": 1, "type": "assistant_message",
                   "payload": {"content": [{"type": "text", "text": "analyzing"}]}}
        yield {"seq": 2, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "DONE-E2E"},
                           "error": None}}


async def _seed(factory):
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T1", display_name="A",
        access_token="xoxb-1", refresh_token=None, token_expires_at=None,
        cp_api_key="tk_live_z", scopes="", metadata={}, master_key=KEY,
    )
    binding = build_binding_row(connection_id=conn_row["id"], container_id="cnt_1",
                                tenant_id="ten_1", enabled=True,
                                resource_filters={"channels": ["C1"]})
    rule = dict(id=new_id("rul"), connection_id=conn_row["id"], tenant_id="ten_1",
                priority=10, match={"channel": "C1"}, target={"container_id": "cnt_1"},
                input_template="{{ text }}", surface=["reasoning", "result"],
                enabled=True, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    insert_conn = {k: v for k, v in conn_row.items() if not k.startswith("_")}
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**insert_conn))
        await s.execute(sa.insert(container_bindings).values(**binding))
        await s.execute(sa.insert(routing_rules).values(**rule))
        await s.commit()


@pytest.mark.asyncio
async def test_full_loop_and_dedupe():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    await _seed(factory)

    provider, cp = FakeProvider(), FakeCP()
    # team_id matches the seeded connection's external_id so tenant routing works.
    payload = {"type": "event_callback", "event_id": "Ev1", "team_id": "T1",
               "event": {"type": "app_mention", "text": "<@U0> go",
                         "channel": "C1", "ts": "100", "user": "U9"}}

    # C2: handle_event now returns immediately; relay runs in the background task.
    bt = BackgroundTasks()
    r1 = await handle_event(provider=provider, payload=payload, factory=factory,
                            cp_client=cp, master_key=KEY, coalesce_ms=0,
                            background_tasks=bt)
    assert r1["status"] == "triggered"
    await bt()  # drive the relay to completion before checking output
    assert any("DONE-E2E" in u for u in provider.updates)

    # Same delivery id again -> deduped, no second submit.
    bt2 = BackgroundTasks()
    r2 = await handle_event(provider=provider, payload=payload, factory=factory,
                            cp_client=cp, master_key=KEY, coalesce_ms=0,
                            background_tasks=bt2)
    assert r2["status"] == "duplicate"
    assert cp.submits == 1

    async with factory() as s:
        deliv = (await s.execute(sa.select(deliveries))).mappings().all()
        whk = (await s.execute(sa.select(webhook_events))).mappings().all()
    assert len(deliv) == 1
    assert deliv[0]["state"] == "done"
    assert len(whk) == 1
