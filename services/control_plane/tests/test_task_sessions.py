"""Unit tests for driver-sessions wiring in submit_task_core.

Mirrors the fake-session pattern in test_task_submit_admission.py: no real DB
or docker, just a fake AsyncSession matching on SQL text substrings.
"""
from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import control_plane.routers.tasks as tasks_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)
_APP = create_app(_SETTINGS)

TENANT_ID = "ten_1"
CONTAINER_ID = "ctr_sessions_1"


class _FakeContainerRow:
    id = CONTAINER_ID
    tenant_id = TENANT_ID
    status = "running"
    docker_name = "agent-sessions-test"
    volume_name = "vol-sessions"
    image_tag = "latest"
    image_variant = "full"
    shim_token = "tok"
    config = {"driver": "vanilla", "model": "gpt-4o", "tools": []}
    resources: dict = {}
    name = "test"
    external_id = None
    git_mode = "snapshot"


_TENANT_LIMITS = {
    "max_running_containers": 5,
    "max_concurrent_tasks_per_container": 4,
    "max_containers": 100,
    "default_max_iterations": 30,
    "default_max_tokens": 200000,
    "default_task_timeout_seconds": 1800,
}

_FAKE_CIPHERTEXT = base64.b64encode(json.dumps({"key": "sk-test-1234"}).encode()).decode()


class _FakeResult:
    def __init__(self, value: Any = None, scalar: int = 0, scalar_none: Any = 0) -> None:
        self._value = value
        self._scalar = scalar
        self._scalar_none = scalar_none

    def first(self) -> Any:
        return self._value

    def scalar(self) -> int:
        return self._scalar

    def scalar_one(self) -> int:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar_none

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list:
        return []


class _FakeMappingsResult:
    def mappings(self) -> _FakeMappingsResult:
        return self

    def first(self) -> dict:  # type: ignore[type-arg]
        return {
            "provider": "anthropic", "auth_method": "api_key", "status": "active",
            "token_expires_at": None, "ciphertext": _FAKE_CIPHERTEXT, "iv": "", "tag": "",
        }

    def all(self) -> list:  # type: ignore[type-arg]
        return [self.first()]


class _FakeSession:
    """Fake AsyncSession. `session_rows` simulates prior `tasks` rows sharing a
    session_id: a list of (driver, status) tuples the precheck queries see."""

    def __init__(self, session_rows: list[tuple[str, str]] | None = None) -> None:
        self.session_rows = session_rows or []

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        s = str(stmt).lower()

        if "tenants" in s and "limits" in s:
            return _FakeResult(scalar_none=_TENANT_LIMITS)
        if "containers" in s and "tenant_id" in s and "count" not in s:
            return _FakeResult(value=_FakeContainerRow())
        # Session driver-lock query: SELECT tasks.driver ... ORDER BY created_at LIMIT 1
        if "session_id" in s and "driver" in s and "order by" in s:
            driver = self.session_rows[0][0] if self.session_rows else None
            return _FakeResult(scalar_none=driver)
        # Session busy query: SELECT count(*) ... WHERE session_id = ... status IN (...)
        if "session_id" in s and "count" in s:
            busy = any(status in ("pending", "running") for _, status in self.session_rows)
            return _FakeResult(scalar=1 if busy else 0)
        # Inflight (container concurrency) count — scalar_one()
        if "count" in s and "tasks" in s:
            return _FakeResult(scalar=0)
        if "credentials" in s:
            return _FakeMappingsResult()
        return _FakeResult()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


_MEMBER_PRINCIPAL = Principal(tenant_id=TENANT_ID, role="member", is_staff=False, user_id=None)


@pytest.fixture
def app_client_factory(monkeypatch: pytest.MonkeyPatch):
    """Returns a factory(session_rows) -> AsyncClient with dependencies overridden."""

    async def fake_bring(*a: Any, **k: Any) -> None:
        return None

    captured: dict[str, Any] = {}

    async def fake_forward(request: Any, row: Any, shim_req: Any, session: Any, task_id: str) -> dict:
        captured["shim_req"] = shim_req
        return {"status": "running"}

    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", fake_bring)
    monkeypatch.setattr(tasks_mod, "forward_to_shim", fake_forward)
    monkeypatch.setattr(tasks_mod, "decrypt_row", lambda row, key: "sk-fake-key")
    monkeypatch.setattr(tasks_mod, "load_key_from_env", lambda: b"fake-key-32-bytes-long----------")

    def _factory(session_rows: list[tuple[str, str]] | None = None) -> tuple[AsyncClient, dict]:
        fake_session = _FakeSession(session_rows)

        async def _fake_session_dep() -> AsyncIterator[_FakeSession]:
            yield fake_session

        _APP.dependency_overrides[resolve_principal] = lambda: _MEMBER_PRINCIPAL
        _APP.dependency_overrides[tasks_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
        transport = ASGITransport(app=_APP)  # type: ignore[arg-type]
        return AsyncClient(transport=transport, base_url="http://test"), captured

    yield _factory
    _APP.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_new_session_id_succeeds_and_is_not_a_continuation(app_client_factory):
    client, captured = app_client_factory(session_rows=[])
    async with client as c:
        r = await c.post(
            f"/v1/containers/{CONTAINER_ID}/tasks",
            json={"prompt": "hi", "session_id": "sess-new"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == "sess-new"
    assert captured["shim_req"].session_id == "sess-new"
    assert captured["shim_req"].session_is_continuation is False


@pytest.mark.asyncio
async def test_submit_existing_session_id_is_a_continuation(app_client_factory):
    client, captured = app_client_factory(session_rows=[("vanilla", "completed")])
    async with client as c:
        r = await c.post(
            f"/v1/containers/{CONTAINER_ID}/tasks",
            json={"prompt": "hi", "session_id": "sess-existing"},
        )
    assert r.status_code == 200, r.text
    assert captured["shim_req"].session_is_continuation is True


@pytest.mark.asyncio
async def test_submit_no_session_id_unaffected(app_client_factory):
    client, captured = app_client_factory(session_rows=[])
    async with client as c:
        r = await c.post(f"/v1/containers/{CONTAINER_ID}/tasks", json={"prompt": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] is None
    assert captured["shim_req"].session_id is None
    assert captured["shim_req"].session_is_continuation is False


@pytest.mark.asyncio
async def test_submit_session_driver_mismatch_returns_409(app_client_factory):
    client, _ = app_client_factory(session_rows=[("codex", "completed")])
    async with client as c:
        r = await c.post(
            f"/v1/containers/{CONTAINER_ID}/tasks",
            json={"prompt": "hi", "session_id": "sess-mismatch"},
        )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "session_driver_mismatch"


@pytest.mark.asyncio
async def test_submit_session_busy_returns_409(app_client_factory):
    client, _ = app_client_factory(session_rows=[("vanilla", "running")])
    async with client as c:
        r = await c.post(
            f"/v1/containers/{CONTAINER_ID}/tasks",
            json={"prompt": "hi", "session_id": "sess-busy"},
        )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "session_busy"


@pytest.mark.asyncio
async def test_list_tasks_filters_by_session_id(monkeypatch):
    class _ListSession(_FakeSession):
        async def execute(self, stmt: Any, params: Any = None) -> Any:
            s = str(stmt).lower()
            if "containers" in s and "tenant_id" in s and "count" not in s:
                return _FakeResult(value=_FakeContainerRow())
            if "from tasks" in s and "session_id" in s and "group by" not in s:
                # list_tasks path — record whether the filter was applied
                self.filtered = "session_id =" in s or "session_id ==" in s
                return _FakeResult()
            return await super().execute(stmt, params)

    fake_session = _ListSession()

    async def _fake_session_dep():
        yield fake_session

    _APP.dependency_overrides[resolve_principal] = lambda: _MEMBER_PRINCIPAL
    _APP.dependency_overrides[tasks_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    try:
        transport = ASGITransport(app=_APP)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get(f"/v1/containers/{CONTAINER_ID}/tasks", params={"session_id": "sess-1"})
    finally:
        _APP.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert fake_session.filtered is True


@pytest.mark.asyncio
async def test_list_sessions_groups_by_session_id():
    from datetime import UTC, datetime

    class _Row:
        session_id = "sess-1"
        driver = "vanilla"
        task_count = 3
        first_created_at = datetime(2026, 7, 1, tzinfo=UTC)
        last_created_at = datetime(2026, 7, 2, tzinfo=UTC)
        busy = False

    class _SessionsListSession(_FakeSession):
        async def execute(self, stmt: Any, params: Any = None) -> Any:
            s = str(stmt).lower()
            if "containers" in s and "tenant_id" in s and "count" not in s:
                return _FakeResult(value=_FakeContainerRow())
            if "group by" in s and "session_id" in s:
                class _R:
                    def all(self_inner):
                        return [_Row()]
                return _R()
            return await super().execute(stmt, params)

    fake_session = _SessionsListSession()

    async def _fake_session_dep():
        yield fake_session

    _APP.dependency_overrides[resolve_principal] = lambda: _MEMBER_PRINCIPAL
    _APP.dependency_overrides[tasks_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    try:
        transport = ASGITransport(app=_APP)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get(f"/v1/containers/{CONTAINER_ID}/sessions")
    finally:
        _APP.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions"] == [{
        "session_id": "sess-1", "driver": "vanilla", "task_count": 3,
        "first_created_at": "2026-07-01T00:00:00+00:00",
        "last_created_at": "2026-07-02T00:00:00+00:00",
        "busy": False,
    }]
