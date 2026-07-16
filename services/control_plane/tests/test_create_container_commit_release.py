from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.containers as containers_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.docker_ctl.provision import ProvisionResult

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed", seed_api_key="tk_live_seed", seed_llm_api_key="",
    agent_image_tag="test", internal_network="test",
    readyz_timeout_seconds=1.0, shim_port=8080,
)
_APP = create_app(_SETTINGS)
_PRINCIPAL = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_1")


class _FakeResult:
    def __init__(self, value: Any = None, scalar: Any = 0) -> None:
        self._value, self._scalar = value, scalar

    def first(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeRow:
    def __init__(self) -> None:
        self.id = "con_1"
        self.name = "x"
        self.external_id = None
        self.metadata = {}
        self.status = "running"
        self.image_tag = "test"
        self.image_variant = "full"
        self.template_id = None
        self.config = {"driver": "vanilla", "model": "m", "system_prompt": "",
                        "system_prompt_mode": "augment", "tools": [], "context": {}}
        self.last_task_at = None
        self.created_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        self.error_message = None
        self.git_mode = "snapshot"
        self.mem_limit = "2g"
        self.cpus = 1.0


class _OrderRecordingSession:
    """Same shape as _FakeSession in test_create_container_resources.py, plus
    call-order recording so this test can assert the pre-provision commit
    (which returns the connection to the pool) happens before the
    potentially minutes-long provision call.
    """

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self._row = _FakeRow()

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        if (
            "select limits from tenants" in s
            or "tenants.limits" in s
            or "select tenants.limits" in s
        ):
            return _FakeResult(scalar={})
        if "count(*)" in s and "containers" in s:
            return _FakeResult(scalar=0)
        if "insert into containers" in s:
            self._order.append("insert")
        return _FakeResult(value=self._row)

    async def commit(self) -> None:
        self._order.append("commit")

    async def rollback(self) -> None:
        self._order.append("rollback")


def _make_client(order: list[str]) -> TestClient:
    session = _OrderRecordingSession(order)

    async def _fake_session_dep() -> AsyncIterator[_OrderRecordingSession]:
        yield session

    async def fake_provision_container(**kwargs):
        order.append("provision")
        return ProvisionResult(docker_name="agent-x", volume_name="vol-x", shim_token="tok")

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    containers_mod.provision_container = fake_provision_container  # type: ignore[assignment]
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


def test_connection_released_before_provision() -> None:
    order: list[str] = []
    client = _make_client(order)
    resp = client.post(
        "/v1/containers",
        json={
            "name": "x",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7", "system_prompt": "",
                       "system_prompt_mode": "augment", "tools": [], "context": {}},
        },
    )
    assert resp.status_code == 201, resp.text
    # The read-only transaction must be committed (connection back to the pool)
    # BEFORE the potentially minutes-long provision starts.
    assert "provision" in order and "commit" in order
    assert order.index("commit") < order.index("provision")
