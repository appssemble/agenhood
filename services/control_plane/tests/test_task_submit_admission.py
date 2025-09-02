"""Unit tests for Task 11: bring_to_running wired into task submission.

Tests verify:
1. bring_to_running is called BEFORE forward_to_shim (ordering)
2. 503 running_capacity_exhausted from bring_to_running propagates
3. 409 container_not_runnable from bring_to_running propagates

All tests use monkeypatch + dependency_overrides; no real DB or docker needed.
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
from control_plane.errors import APIError

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# App / settings
# ---------------------------------------------------------------------------

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
CONTAINER_ID = "ctr_submit_1"

# ---------------------------------------------------------------------------
# Fake DB that satisfies submit_task's queries
# ---------------------------------------------------------------------------


class _FakeContainerRow:
    id = CONTAINER_ID
    tenant_id = TENANT_ID
    status = "running"
    docker_name = "agent-submit-test"
    volume_name = "vol-submit"
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


# A fake encrypted credential row (base64-encoded JSON)
_FAKE_CIPHERTEXT = base64.b64encode(
    json.dumps({"key": "sk-test-1234"}).encode()
).decode()


class _FakeSession:
    """Fake AsyncSession for submit_task: returns container row, tenant limits,
    zero inflight tasks, and a stub credential row."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        s = str(stmt).lower()
        self.executed.append(s[:80])

        # Tenant limits: load_tenant_limits calls scalar_one_or_none()
        if "tenants" in s and "limits" in s:
            return _FakeResult(scalar_none=_TENANT_LIMITS)

        # Container select (load_owned_container) — returns row via first()
        if "containers" in s and "tenant_id" in s and "count" not in s:
            return _FakeResult(value=_FakeContainerRow())

        # Inflight task count — scalar_one()
        if "count" in s and "tasks" in s:
            return _FakeResult(scalar=0)

        # Credential lookup (SELECT FROM credentials) — needs mappings().first()
        if "credentials" in s:
            return _FakeMappingsResult()

        # Any INSERT/UPDATE — no-op
        return _FakeResult()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _FakeMappingsResult:
    """Fake result for the credential mappings().first()/.all() calls."""

    class _Cred(dict):  # type: ignore[type-arg]
        pass

    def mappings(self) -> _FakeMappingsResult:
        return self

    def first(self) -> dict:  # type: ignore[type-arg]
        # Must match what decrypt_row expects; it base64-decodes the ciphertext.
        return {
            "provider": "anthropic",
            "auth_method": "api_key",
            "status": "active",
            "token_expires_at": None,
            "ciphertext": _FAKE_CIPHERTEXT,
            "iv": "",
            "tag": "",
        }

    def all(self) -> list:  # type: ignore[type-arg]
        # Return a list with a single api_key credential row so pick_provider_credential
        # selects it (new multi-row credential lookup path).
        return [self.first()]


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

_MEMBER_PRINCIPAL = Principal(
    tenant_id=TENANT_ID, role="member", is_staff=False, user_id=None
)


# ---------------------------------------------------------------------------
# submit_ctx fixture
# ---------------------------------------------------------------------------


class _SubmitCtx:
    """Thin helper that drives the submit route against the fake app."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def submit_raw(self, *, prompt: str) -> Any:
        return await self._client.post(
            f"/v1/containers/{CONTAINER_ID}/tasks",
            json={"prompt": prompt},
        )

    async def submit(self, *, prompt: str) -> None:
        r = await self.submit_raw(prompt=prompt)
        # For ordering tests where everything is mocked, a non-error response is fine.
        assert r.status_code < 500, f"Unexpected server error: {r.text}"


@pytest.fixture
async def submit_ctx() -> AsyncIterator[_SubmitCtx]:
    """Provide a SubmitCtx backed by a fake app with dependency overrides."""
    fake_session = _FakeSession()

    async def _fake_session_dep() -> AsyncIterator[_FakeSession]:
        yield fake_session

    _APP.dependency_overrides[resolve_principal] = lambda: _MEMBER_PRINCIPAL
    _APP.dependency_overrides[tasks_mod._session] = _fake_session_dep  # type: ignore[attr-defined]

    transport = ASGITransport(app=_APP)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield _SubmitCtx(client)

    _APP.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_brings_container_to_running_before_forwarding(
    monkeypatch: pytest.MonkeyPatch, submit_ctx: _SubmitCtx
) -> None:
    """bring_to_running must be called before forward_to_shim."""
    order: list[str] = []

    async def fake_bring(
        db: Any, dock: Any, shim: Any, cid: str, tenant_id: str, *, limit: int, **kwargs: Any
    ) -> None:
        order.append("bring")

    async def fake_forward(
        request: Any, row: Any, shim_req: Any, session: Any, task_id: str
    ) -> dict:  # type: ignore[type-arg]
        order.append("forward")
        return {"status": "running"}

    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", fake_bring)
    monkeypatch.setattr(tasks_mod, "forward_to_shim", fake_forward)

    # Patch credential lookup to avoid needing a real encryption key.
    monkeypatch.setattr(tasks_mod, "decrypt_row", lambda row, key: "sk-fake-key")
    monkeypatch.setattr(tasks_mod, "load_key_from_env", lambda: b"fake-key-32-bytes-long----------")

    await submit_ctx.submit(prompt="hi")
    assert "bring" in order, "bring_to_running was not called"
    assert "forward" in order, "forward_to_shim was not called"
    assert order.index("bring") < order.index("forward")


@pytest.mark.asyncio
async def test_submit_propagates_503_running_capacity_exhausted(
    monkeypatch: pytest.MonkeyPatch, submit_ctx: _SubmitCtx
) -> None:
    """503 running_capacity_exhausted from bring_to_running must surface in response."""

    async def boom(*a: Any, **k: Any) -> None:
        raise APIError(503, "running_capacity_exhausted", "busy")

    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", boom)

    r = await submit_ctx.submit_raw(prompt="hi")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "running_capacity_exhausted"


@pytest.mark.asyncio
async def test_submit_propagates_409_container_not_runnable(
    monkeypatch: pytest.MonkeyPatch, submit_ctx: _SubmitCtx
) -> None:
    """409 container_not_runnable from bring_to_running must surface in response."""

    async def boom(*a: Any, **k: Any) -> None:
        raise APIError(409, "container_not_runnable", "provisioning")

    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", boom)

    r = await submit_ctx.submit_raw(prompt="hi")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "container_not_runnable"


@pytest.mark.asyncio
async def test_submit_linked_container_disables_snapshots_and_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A linked (pull-mode) container must submit a shim request with
    git_snapshots=False and git_push=None — the shim must not commit or push the
    cloned workspace back up."""
    captured: dict[str, Any] = {}

    class _LinkedRow(_FakeContainerRow):
        git_mode = "linked"

    class _LinkedSession(_FakeSession):
        async def execute(self, stmt: Any, params: Any = None) -> Any:
            s = str(stmt).lower()
            if "containers" in s and "tenant_id" in s and "count" not in s:
                return _FakeResult(value=_LinkedRow())
            return await super().execute(stmt, params)

    async def fake_bring(*a: Any, **k: Any) -> None:
        return None

    async def fake_forward(
        request: Any, row: Any, shim_req: Any, session: Any, task_id: str
    ) -> dict:  # type: ignore[type-arg]
        captured["shim_req"] = shim_req
        return {"status": "running"}

    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", fake_bring)
    monkeypatch.setattr(tasks_mod, "forward_to_shim", fake_forward)
    monkeypatch.setattr(tasks_mod, "decrypt_row", lambda row, key: "sk-fake-key")
    monkeypatch.setattr(
        tasks_mod, "load_key_from_env", lambda: b"fake-key-32-bytes-long----------"
    )

    fake_session = _LinkedSession()

    async def _fake_session_dep() -> AsyncIterator[_LinkedSession]:
        yield fake_session

    _APP.dependency_overrides[resolve_principal] = lambda: _MEMBER_PRINCIPAL
    _APP.dependency_overrides[tasks_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    try:
        transport = ASGITransport(app=_APP)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                f"/v1/containers/{CONTAINER_ID}/tasks", json={"prompt": "hi"}
            )
    finally:
        _APP.dependency_overrides.clear()

    assert r.status_code < 500, r.text
    shim_req = captured.get("shim_req")
    assert shim_req is not None, "forward_to_shim was not called"
    assert shim_req.git_snapshots is False
    assert shim_req.git_push is None
