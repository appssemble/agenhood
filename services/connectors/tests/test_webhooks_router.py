from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.app import create_app
from connectors.connections_service import build_connection_row
from connectors.ids import new_id
from connectors.models import NormalizedEvent
from connectors.tables import (
    connections,
    container_bindings,
    deliveries,
    metadata,
    routing_rules,
)

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


def _strip_helpers(row: dict) -> dict:  # type: ignore[type-arg]
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeProvider:
    name = "slack"

    def __init__(self) -> None:
        self.initial_posts: list[str] = []
        self.updates: list[str] = []

    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> bool:
        return True

    def normalize_event(self, payload: dict[str, Any]) -> NormalizedEvent | None:
        if payload.get("type") != "event_callback":
            return None
        return NormalizedEvent(
            provider="slack",
            event_type="app_mention",
            external_delivery_id="evt_test_1",
            resource="C1",
            thread_key="C1:ts1",
            text="hello bot",
            origin_ref={"channel": "C1", "thread_ts": "ts1"},
            actor="U1",
            external_id=payload.get("team_id"),
        )

    async def mint_token(self, connection_row: dict[str, Any], master_key: bytes) -> str:
        return "tok"

    async def post_initial(
        self, token: str, origin_ref: dict[str, Any], body: str
    ) -> dict[str, Any]:
        self.initial_posts.append(body)
        return {"channel": "C1", "ts": "99"}

    async def update_message(
        self, token: str, handle: dict[str, Any], body: str
    ) -> None:
        self.updates.append(body)


class FakeCP:
    async def submit_task(
        self, *, container_id: str, api_key: str, prompt: str, metadata: dict[str, Any]
    ) -> str:
        return "tsk_1"

    async def stream_events(
        self,
        *,
        container_id: str,
        task_id: str,
        api_key: str,
        after_seq: int = 0,
    ):  # type: ignore[return]  # async generator
        yield {
            "seq": 1,
            "type": "status_change",
            "payload": {
                "to": "succeeded",
                "result": {"output": "OK"},
                "error": None,
            },
        }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):  # type: ignore[return]
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(KEY).decode())

    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    now = datetime.now(UTC)

    async def _setup() -> None:
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)

        conn_row = build_connection_row(
            tenant_id="ten_1",
            provider="slack",
            external_id="T123",
            display_name="Acme Slack",
            access_token="xoxb-abc1234",
            refresh_token=None,
            token_expires_at=None,
            cp_api_key="test-api-key",
            scopes="chat:write",
            metadata={},
            master_key=KEY,
        )
        conn_id = conn_row["id"]

        bnd_id = new_id("bnd")
        rule_id = new_id("rul")

        async with eng.begin() as txn:
            await txn.execute(
                sa.insert(connections).values(**_strip_helpers(conn_row))
            )
            await txn.execute(
                sa.insert(container_bindings).values(
                    id=bnd_id,
                    connection_id=conn_id,
                    container_id="cnt_1",
                    tenant_id="ten_1",
                    enabled=True,
                    resource_filters={},
                    created_at=now,
                    updated_at=now,
                )
            )
            await txn.execute(
                sa.insert(routing_rules).values(
                    id=rule_id,
                    connection_id=conn_id,
                    tenant_id="ten_1",
                    priority=50,
                    match={"channel": "C1"},
                    target={"container_id": "cnt_1"},
                    input_template="{{ text }}",
                    surface=["result"],
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )

        await eng.dispose()

    asyncio.run(_setup())

    app = create_app(start_background=False)
    eng = create_async_engine(db_url)
    app.state.engine = eng
    app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
    app.state.master_key = KEY
    app.state.providers = {"slack": FakeProvider()}
    app.state.cp_client = FakeCP()

    return TestClient(app), db_url


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_webhook_unknown_provider_returns_404(client) -> None:
    tc, _ = client
    r = tc.post("/v1/webhooks/unknown", content=b"{}")
    assert r.status_code == 404


def test_slack_url_verification_handshake(client) -> None:
    tc, _ = client
    payload = json.dumps({"type": "url_verification", "challenge": "abc123"})
    r = tc.post(
        "/v1/webhooks/slack",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.text == "abc123"


def test_webhook_slack_triggers_delivery(client) -> None:
    tc, db_url = client

    payload = {
        "type": "event_callback",
        "event_id": "evt_test_1",
        "event": {
            "type": "app_mention",
            "channel": "C1",
            "ts": "ts1",
            "text": "hello bot",
            "user": "U1",
        },
        "team_id": "T123",
    }

    r = tc.post(
        "/v1/webhooks/slack",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "triggered"
    assert body["task_id"] == "tsk_1"

    # Verify exactly one deliveries row with the right task_id
    async def _read_deliveries() -> list[dict]:  # type: ignore[return]
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            rows = (await conn.execute(sa.select(deliveries))).mappings().all()
        await eng.dispose()
        return [dict(r) for r in rows]

    rows = asyncio.run(_read_deliveries())
    assert len(rows) == 1
    assert rows[0]["task_id"] == "tsk_1"

    # Verify FakeProvider recorded an update containing the result text "OK"
    fake_provider: FakeProvider = tc.app.state.providers["slack"]
    assert fake_provider.initial_posts, "post_initial was never called"
    assert any("OK" in u for u in fake_provider.updates), (
        f"expected 'OK' in updates, got: {fake_provider.updates}"
    )


def test_webhook_duplicate_event_returns_duplicate(client) -> None:
    """A second POST with the same event_id must be rejected as duplicate."""
    tc, _ = client

    payload = {
        "type": "event_callback",
        "event_id": "evt_dup_1",
        "event": {
            "type": "app_mention",
            "channel": "C1",
            "ts": "ts2",
            "text": "second mention",
            "user": "U1",
        },
        "team_id": "T123",
    }
    raw = json.dumps(payload)
    headers = {"Content-Type": "application/json"}

    r1 = tc.post("/v1/webhooks/slack", content=raw, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == "triggered"

    r2 = tc.post("/v1/webhooks/slack", content=raw, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
