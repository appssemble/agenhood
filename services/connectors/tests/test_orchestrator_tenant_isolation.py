"""
Unit test proving C1 (cross-tenant routing leak) is closed.

A connection seeded for workspace T1 must NEVER receive an event whose
external_id is T_OTHER — the result must be no_route and no delivery row
or submit_task call may occur.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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

pytestmark = pytest.mark.unit
KEY = os.urandom(32)


class FakeProvider:
    name = "slack"

    def __init__(self, *, external_id: str | None) -> None:
        self._external_id = external_id

    def normalize_event(self, payload: dict) -> NormalizedEvent:  # type: ignore[type-arg]
        return NormalizedEvent(
            provider="slack",
            event_type="app_mention",
            external_delivery_id=payload.get("event_id", "ev_iso"),
            resource="C1",
            thread_key="C1:ts1",
            text="hi",
            origin_ref={"channel": "C1", "thread_ts": "ts1"},
            external_id=self._external_id,
        )

    async def mint_token(self, row: dict, master_key: bytes) -> str:  # type: ignore[type-arg]
        return "tok"

    async def post_initial(self, token: str, origin_ref: dict, body: str) -> dict:  # type: ignore[type-arg]
        return {"channel": "C1", "ts": "1"}

    async def update_message(self, token: str, handle: dict, body: str) -> None:  # type: ignore[type-arg]
        pass


class FakeCP:
    def __init__(self) -> None:
        self.submits = 0

    async def submit_task(  # type: ignore[type-arg]
        self, *, container_id: str, api_key: str, prompt: str, metadata: dict
    ) -> str:
        self.submits += 1
        return "tsk_should_not_happen"

    async def stream_events(  # type: ignore[return]
        self, *, container_id: str, task_id: str, api_key: str, after_seq: int = 0
    ):
        yield {"seq": 1, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "ok"}, "error": None}}


async def _seed(factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T1",
        display_name="Tenant-1 Slack", access_token="xoxb-1",
        refresh_token=None, token_expires_at=None, cp_api_key="tk_live_x",
        scopes="", metadata={}, master_key=KEY,
    )
    bnd_id = new_id("bnd")
    rule_id = new_id("rul")
    insert_conn = {k: v for k, v in conn_row.items() if not k.startswith("_")}
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**insert_conn))
        await s.execute(
            sa.insert(container_bindings).values(
                id=bnd_id, connection_id=conn_row["id"],
                container_id="cnt_1", tenant_id="ten_1",
                enabled=True, resource_filters={},
                created_at=now, updated_at=now,
            )
        )
        await s.execute(
            sa.insert(routing_rules).values(
                id=rule_id, connection_id=conn_row["id"],
                tenant_id="ten_1", priority=10,
                match={}, target={"container_id": "cnt_1"},
                input_template="{{ text }}", surface=["result"],
                enabled=True, created_at=now, updated_at=now,
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_event_from_different_workspace_is_not_routed() -> None:
    """
    Isolation check: an event arriving with external_id="T_OTHER" must not
    be routed to the connection seeded for external_id="T1".
    """
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    await _seed(factory)

    provider = FakeProvider(external_id="T_OTHER")
    cp = FakeCP()
    payload = {"event_id": "ev_iso_other"}

    bt = BackgroundTasks()
    result = await handle_event(
        provider=provider, payload=payload, factory=factory,
        cp_client=cp, master_key=KEY, coalesce_ms=0,
        background_tasks=bt,
    )

    assert result == {"status": "no_route"}, f"expected no_route, got {result}"
    assert cp.submits == 0, "submit_task must not be called for a foreign workspace"

    async with factory() as s:
        rows = (await s.execute(sa.select(deliveries))).mappings().all()
    assert len(rows) == 0, "no delivery row must be created for a cross-tenant event"


@pytest.mark.asyncio
async def test_event_from_correct_workspace_is_routed() -> None:
    """
    Positive counterpart: same connection, correct external_id="T1" → triggered.
    """
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    await _seed(factory)

    provider = FakeProvider(external_id="T1")
    cp = FakeCP()
    payload = {"event_id": "ev_iso_match"}

    bt = BackgroundTasks()
    result = await handle_event(
        provider=provider, payload=payload, factory=factory,
        cp_client=cp, master_key=KEY, coalesce_ms=0,
        background_tasks=bt,
    )

    assert result["status"] == "triggered", f"expected triggered, got {result}"
    assert cp.submits == 1

    async with factory() as s:
        rows = (await s.execute(sa.select(deliveries))).mappings().all()
    assert len(rows) == 1


class FakeCPRaisesOnce:
    """submit_task raises on the first call, succeeds on the second."""

    def __init__(self) -> None:
        self.calls = 0

    async def submit_task(  # type: ignore[type-arg]
        self, *, container_id: str, api_key: str, prompt: str, metadata: dict
    ) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("CP unavailable (simulated)")
        return "tsk_retry_ok"

    async def stream_events(  # type: ignore[return]
        self, *, container_id: str, task_id: str, api_key: str, after_seq: int = 0
    ):
        yield {"seq": 1, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "ok"}, "error": None}}


@pytest.mark.asyncio
async def test_submit_failure_releases_dedupe_claim() -> None:
    """
    I3: when submit_task raises, the webhook_events claim must be deleted so a
    provider retry (same event_id) is NOT treated as duplicate and can succeed.
    """
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    await _seed(factory)

    provider = FakeProvider(external_id="T1")
    cp = FakeCPRaisesOnce()
    payload = {"event_id": "ev_retry"}

    # First attempt: submit_task raises → orchestrator must re-raise.
    bt1 = BackgroundTasks()
    with pytest.raises(RuntimeError, match="CP unavailable"):
        await handle_event(
            provider=provider, payload=payload, factory=factory,
            cp_client=cp, master_key=KEY, coalesce_ms=0,
            background_tasks=bt1,
        )

    # The dedupe claim must have been removed so the next call is not "duplicate".
    async with factory() as s:
        wh_rows = (await s.execute(sa.select(webhook_events))).mappings().all()
    assert len(wh_rows) == 0, "dedupe row must be deleted after submit failure"

    # Second attempt (provider retry): must succeed, not return "duplicate".
    bt2 = BackgroundTasks()
    result = await handle_event(
        provider=provider, payload=payload, factory=factory,
        cp_client=cp, master_key=KEY, coalesce_ms=0,
        background_tasks=bt2,
    )
    assert result["status"] == "triggered", f"retry must succeed, got {result}"
    assert cp.calls == 2
