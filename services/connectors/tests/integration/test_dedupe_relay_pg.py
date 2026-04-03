from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa

from connectors.connections_service import build_connection_row
from connectors.ids import new_id
from connectors.models import NormalizedEvent
from connectors.tables import (
    connections,
    container_bindings,
    deliveries,
    routing_rules,
    webhook_events,
)

pytestmark = pytest.mark.integration


class FakeProvider:
    name = "slack"

    def __init__(self) -> None:
        self.updates: list[str] = []

    def verify_webhook(self, headers, raw_body) -> bool:
        return True

    def normalize_event(self, payload) -> NormalizedEvent | None:
        if payload.get("type") != "event_callback":
            return None
        ev = payload["event"]
        return NormalizedEvent(
            provider="slack", event_type="app_mention",
            external_delivery_id=payload["event_id"], resource=ev["channel"],
            thread_key=f"{ev['channel']}:{ev['ts']}", text=ev["text"],
            origin_ref={"channel": ev["channel"], "thread_ts": ev["ts"]},
            external_id=payload.get("team_id"))

    async def mint_token(self, row, master_key) -> str:
        return "tok"

    async def post_initial(self, token, origin_ref, body) -> dict[str, Any]:
        return {"channel": origin_ref["channel"], "ts": "msg1"}

    async def update_message(self, token, handle, body) -> None:
        self.updates.append(body)


class FakeCP:
    def __init__(self) -> None:
        self.submits = 0

    async def submit_task(self, *, container_id, api_key, prompt, metadata) -> str:
        self.submits += 1
        return "tsk_pg"

    async def stream_events(self, *, container_id, task_id, api_key, after_seq=0):
        yield {"seq": 1, "type": "assistant_message",
               "payload": {"content": [{"type": "text", "text": "analyzing"}]}}
        yield {"seq": 2, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "PG-DONE"},
                           "error": None}}


async def _seed(factory, master_key) -> None:
    now = datetime.now(UTC)
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T1", display_name="A",
        access_token="xoxb-1", refresh_token=None, token_expires_at=None,
        cp_api_key="tk_live_z", scopes="", metadata={}, master_key=master_key)
    insert = {k: v for k, v in conn_row.items() if not k.startswith("_")}
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**insert))
        await s.execute(sa.insert(container_bindings).values(
            id=new_id("bnd"), connection_id=conn_row["id"], container_id="cnt_1",
            tenant_id="ten_1", enabled=True, resource_filters={},
            created_at=now, updated_at=now))
        await s.execute(sa.insert(routing_rules).values(
            id=new_id("rul"), connection_id=conn_row["id"], tenant_id="ten_1",
            priority=10, match={"channel": "C1"}, target={"container_id": "cnt_1"},
            input_template="{{ text }}", surface=["reasoning", "result"],
            enabled=True, created_at=now, updated_at=now))
        await s.commit()


def _payload(event_id: str) -> str:
    return json.dumps({
        "type": "event_callback", "event_id": event_id, "team_id": "T1",
        "event": {"type": "app_mention", "text": "<@U0> go",
                  "channel": "C1", "ts": "100", "user": "U9"}})


@pytest.mark.asyncio
async def test_full_loop_and_dedupe_on_postgres(pg_app, session_factory, master_key):
    await _seed(session_factory, master_key)
    provider, cp = FakeProvider(), FakeCP()

    # Use TestClient as a context manager so all requests share one anyio portal
    # and one event loop — asyncpg connections are established once in that loop
    # and reused for both requests.  Without the context manager each .post()
    # opens its own portal (a new event loop) and asyncpg raises
    # "Future attached to a different loop" on the second checkout.
    with pg_app(providers={"slack": provider}, cp_client=cp) as client:
        r1 = client.post("/v1/webhooks/slack", content=_payload("Ev1"),
                         headers={"Content-Type": "application/json"})
        assert r1.status_code == 200 and r1.json()["status"] == "triggered"
        # TestClient runs BackgroundTasks synchronously after the response, so the
        # relay has completed by the time .post() returns.
        assert any("PG-DONE" in u for u in provider.updates)

        r2 = client.post("/v1/webhooks/slack", content=_payload("Ev1"),
                         headers={"Content-Type": "application/json"})
        assert r2.json()["status"] == "duplicate"
        assert cp.submits == 1

    async with session_factory() as s:
        deliv = (await s.execute(sa.select(deliveries))).mappings().all()
        whk = (await s.execute(sa.select(webhook_events))).mappings().all()
    assert len(deliv) == 1 and deliv[0]["state"] == "done"
    assert deliv[0]["origin_ref"] == {"channel": "C1", "thread_ts": "100"}  # JSONB
    assert len(whk) == 1


@pytest.mark.asyncio
async def test_dedupe_unique_index_is_enforced_by_postgres(session_factory):
    # Two raw claims for the same (provider, external_delivery_id) must collide
    # on the real UNIQUE index — the IntegrityError path that SQLite cannot prove.
    from connectors.webhook_dedupe import claim_delivery

    async with session_factory() as s:
        first = await claim_delivery(s, "slack", "dup-1", "digestA")
        await s.commit()
    async with session_factory() as s:
        second = await claim_delivery(s, "slack", "dup-1", "digestB")
        await s.commit()
    assert first is True and second is False
