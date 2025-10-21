"""Unit tests for the lifecycle route handlers (pause/resume/recover).

All tests use FastAPI TestClient + dependency_overrides so no real DB,
Docker daemon, or shim is needed.  The tests cover only pure pre-docker guards:
  - recover returns 409 when the container is not in 'error'
  - recover returns 403 for a member (admin-only route)
  - pause returns 409 when in-flight tasks exist and force=False

Docker-touching paths (actual pause/resume/recover execution) are covered by
the lifecycle_ops unit tests (test_lifecycle_ops.py).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.containers as containers_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Minimal settings (no real DB — sessions are overridden)
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

# ---------------------------------------------------------------------------
# Fake DB row helpers
# ---------------------------------------------------------------------------

TENANT_ID = "ten_1"
CONTAINER_ID = "ctr_test_1"


class _FakeRow:
    """Minimal container row stand-in."""

    def __init__(self, status: str) -> None:
        self.id = CONTAINER_ID
        self.tenant_id = TENANT_ID
        self.status = status
        self.docker_name = "agent-test"
        self.volume_name = "vol-test"
        self.image_tag = "latest"
        self.image_variant = "full"
        self.shim_token = "tok"
        self.config = {"driver": "vanilla", "model": "gpt-4o", "tools": []}
        self.resources = {}
        self.name = "test"
        self.external_id = None
        self.metadata = {}
        self.template_id = None
        self.last_task_at = None
        self.error_message = None

    def __getattr__(self, item: str) -> Any:
        return None


class _FakeResult:
    def __init__(self, value: Any = None, scalar: int = 0) -> None:
        self._value = value
        self._scalar = scalar

    def first(self) -> Any:
        return self._value

    def scalar(self) -> int:
        return self._scalar

    def scalar_one(self) -> int:
        return self._scalar

    def scalar_one_or_none(self) -> int | None:
        return self._scalar

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return []


class _FakeSession:
    """Stand-in AsyncSession that returns a fixed container row and optionally
    a fixed in-flight task count (for the pause-busy test)."""

    def __init__(self, container_status: str, active_tasks: int = 0) -> None:
        self._row = _FakeRow(container_status)
        self._active = active_tasks

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        # Active task count query (admission.active_task_count)
        if "select count(*) from tasks" in s or "count(*)" in s and "tasks" in s:
            return _FakeResult(scalar=self._active)
        # Container select (load_owned_container)
        return _FakeResult(value=self._row)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Principal factories
# ---------------------------------------------------------------------------

_ADMIN_PRINCIPAL = Principal(
    tenant_id=TENANT_ID, role="admin", is_staff=False, user_id="usr_admin"
)
_MEMBER_PRINCIPAL = Principal(
    tenant_id=TENANT_ID, role="member", is_staff=False, user_id="usr_member"
)

# ---------------------------------------------------------------------------
# Helper: build a TestClient with overridden principal + session
# ---------------------------------------------------------------------------


def _make_client(
    principal: Principal,
    container_status: str = "running",
    active_tasks: int = 0,
) -> TestClient:
    """Return a TestClient with dependency_overrides injected."""

    fake_session = _FakeSession(container_status, active_tasks)

    async def _fake_session_dep() -> AsyncIterator[_FakeSession]:
        yield fake_session

    _APP.dependency_overrides[resolve_principal] = lambda: principal
    _APP.dependency_overrides[containers_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# recover — role gate
# ---------------------------------------------------------------------------


def test_recover_requires_admin() -> None:
    """member principal must receive 403 on the recover route."""
    client = _make_client(_MEMBER_PRINCIPAL, container_status="error")
    r = client.post(f"/v1/containers/{CONTAINER_ID}/recover")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# recover — state guard (pre-docker)
# ---------------------------------------------------------------------------


def test_recover_rejects_when_not_in_error() -> None:
    """Admin calling recover on a running container must get 409."""
    client = _make_client(_ADMIN_PRINCIPAL, container_status="running")
    r = client.post(f"/v1/containers/{CONTAINER_ID}/recover")
    assert r.status_code == 409
    body = r.json()
    # Either a container_not_runnable code or a message mentioning the state guard.
    assert (
        body["error"]["code"] == "container_not_runnable"
        or "error" in body["error"]["message"]
        or "running" in body["error"]["message"]
    )


# ---------------------------------------------------------------------------
# pause — busy guard (pre-docker)
# ---------------------------------------------------------------------------


def test_pause_busy_without_force_409() -> None:
    """Pause without force on a container with in-flight tasks must return 409."""
    client = _make_client(_ADMIN_PRINCIPAL, container_status="running", active_tasks=1)
    r = client.post(f"/v1/containers/{CONTAINER_ID}/pause", json={})
    # lifecycle.pause raises APIError(409, container_not_runnable, ...) synchronously
    # before any docker call when active > 0 and force=False.
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "container_not_runnable"
