"""Route wiring for the paginated task, session and event listings.

The page queries are stubbed; their SQL is covered by test_list_pagination_db.py.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import control_plane.routers.tasks as tasks_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.pagination import encode_cursor

pytestmark = pytest.mark.unit

_APP = create_app(Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
))

CID = "ctr_1"
TS = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _TaskRow:
    id = "tsk_1"
    container_id = CID
    session_id = None
    body: dict = {"prompt": "hi"}  # type: ignore[type-arg]
    status = "succeeded"
    driver = "vanilla"
    model = "m"
    config_snapshot: dict = {"driver": "vanilla", "model": "m"}  # type: ignore[type-arg]
    result = None
    error_code = None
    error_message = None
    iterations_used = 0
    tokens_in = 0
    tokens_out = 0
    started_at = None
    ended_at = None
    created_at = TS


class _SessionRow:
    session_id = "sess_1"
    driver = "vanilla"
    task_count = 2
    first_created_at = TS
    last_created_at = TS
    busy = False


class _EventRow:
    def __init__(self, seq: int) -> None:
        self.seq = seq
        self.type = "log"
        self.ts = TS
        self.payload = {"n": seq}


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[AsyncClient, dict]]:  # type: ignore[type-arg]
    calls: dict[str, Any] = {}

    async def _owned(*_a: Any, **_k: Any) -> Any:
        return object()

    async def _tasks_page(_s: Any, **kw: Any) -> Any:
        calls["tasks"] = kw
        return [_TaskRow()], "next-tasks"

    async def _sessions_page(_s: Any, **kw: Any) -> Any:
        calls["sessions"] = kw
        return [_SessionRow()], None

    async def _events_page(_s: Any, **kw: Any) -> Any:
        calls["events"] = kw
        return [_EventRow(4), _EventRow(5)], 5

    async def _session_dep() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(tasks_mod, "_load_owned_container", _owned)
    monkeypatch.setattr(tasks_mod, "_load_owned_task", _owned)
    monkeypatch.setattr(tasks_mod, "container_tasks_page", _tasks_page)
    monkeypatch.setattr(tasks_mod, "container_sessions_page", _sessions_page)
    monkeypatch.setattr(tasks_mod, "task_events_page", _events_page)
    _APP.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id="ten_1", role="member", is_staff=False, user_id=None
    )
    _APP.dependency_overrides[tasks_mod._session] = _session_dep  # type: ignore[attr-defined]
    try:
        async with AsyncClient(transport=ASGITransport(app=_APP), base_url="http://t") as c:  # type: ignore[arg-type]
            yield c, calls
    finally:
        _APP.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_tasks_default_page_matches_previous_cap(client) -> None:
    c, calls = client
    r = await c.get(f"/v1/containers/{CID}/tasks")
    assert r.status_code == 200, r.text
    assert calls["tasks"]["limit"] == 100
    assert calls["tasks"]["after"] is None
    body = r.json()
    assert [t["task_id"] for t in body["tasks"]] == ["tsk_1"]
    assert body["next_cursor"] == "next-tasks"


@pytest.mark.asyncio
async def test_tasks_passes_filters_clamped_limit_and_cursor(client) -> None:
    c, calls = client
    cursor = encode_cursor(TS, "tsk_9")
    r = await c.get(
        f"/v1/containers/{CID}/tasks",
        params={"limit": 5000, "cursor": cursor, "session_id": "s", "scheduled_task_id": "st"},
    )
    assert r.status_code == 200, r.text
    kw = calls["tasks"]
    assert kw["limit"] == 200
    assert kw["after"] == (TS, "tsk_9")
    assert kw["session_id"] == "s"
    assert kw["scheduled_task_id"] == "st"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["tasks", "sessions"])
async def test_bad_cursor_is_400(client, path: str) -> None:
    c, _ = client
    r = await c.get(f"/v1/containers/{CID}/{path}", params={"cursor": "garbage!"})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.asyncio
async def test_sessions_without_limit_returns_everything(client) -> None:
    c, calls = client
    r = await c.get(f"/v1/containers/{CID}/sessions")
    assert r.status_code == 200, r.text
    assert calls["sessions"]["limit"] is None
    body = r.json()
    assert body["sessions"][0]["session_id"] == "sess_1"
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_sessions_limit_is_clamped(client) -> None:
    c, calls = client
    r = await c.get(f"/v1/containers/{CID}/sessions", params={"limit": 0})
    assert r.status_code == 200, r.text
    assert calls["sessions"]["limit"] == 1


@pytest.mark.asyncio
async def test_events_json_without_limit_returns_everything(client) -> None:
    c, calls = client
    r = await c.get(f"/v1/containers/{CID}/tasks/tsk_1/events", params={"after_seq": 3})
    assert r.status_code == 200, r.text
    assert calls["events"] == {"task_id": "tsk_1", "after_seq": 3, "limit": None}
    body = r.json()
    assert [e["seq"] for e in body["events"]] == [4, 5]
    assert body["next_after_seq"] == 5


@pytest.mark.asyncio
async def test_events_json_limit_is_clamped(client) -> None:
    c, calls = client
    r = await c.get(f"/v1/containers/{CID}/tasks/tsk_1/events", params={"limit": 10**6})
    assert r.status_code == 200, r.text
    assert calls["events"]["limit"] == 5000
