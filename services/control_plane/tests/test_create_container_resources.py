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
TENANT_ID = "ten_1"
_PRINCIPAL = Principal(tenant_id=TENANT_ID, role="admin", is_staff=False, user_id="usr_1")


class _FakeResult:
    def __init__(self, value: Any = None, scalar: int = 0) -> None:
        self._value, self._scalar = value, scalar

    def first(self) -> Any:
        return self._value

    def scalar(self) -> int:
        return self._scalar

    def scalar_one(self) -> int:
        return self._scalar

    def scalar_one_or_none(self) -> int | None:
        return self._scalar


class _FakeRow:
    def __init__(self, mem_limit: str, cpus: float) -> None:
        self.id = "con_1"
        self.name = "x"
        self.external_id = None
        self.metadata = {}
        self.status = "running"
        self.image_tag = "test"
        self.image_variant = "slim"
        self.template_id = None
        self.config = {"driver": "vanilla", "model": "m", "system_prompt": "",
                        "system_prompt_mode": "augment", "tools": [], "context": {}}
        self.last_task_at = None
        self.created_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        self.error_message = None
        self.git_mode = "snapshot"
        self.mem_limit = mem_limit
        self.cpus = cpus


class _FakeSession:
    def __init__(self) -> None:
        self._row = _FakeRow("2g", 1.0)  # slim defaults, as resolved by the handler

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        if (
            "select limits from tenants" in s
            or "tenants.limits" in s
            or "select tenants.limits" in s
        ):
            # load_tenant_limits treats a None scalar as "tenant not found" (the
            # `limits` column is NOT NULL in the real schema), so simulate a
            # tenant with no frozen overrides via an empty dict, not None.
            return _FakeResult(scalar={})
        if "count(*)" in s and "containers" in s:
            return _FakeResult(scalar=0)
        return _FakeResult(value=self._row)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _make_client(captured: dict) -> TestClient:
    fake_session = _FakeSession()

    async def _fake_session_dep() -> AsyncIterator[_FakeSession]:
        yield fake_session

    async def fake_provision_container(**kwargs):
        captured.update(kwargs)
        return ProvisionResult(docker_name="agent-x", volume_name="vol-x", shim_token="tok")

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    containers_mod.provision_container = fake_provision_container  # type: ignore[assignment]
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


def test_create_slim_container_gets_slim_tiered_default() -> None:
    captured: dict = {}
    client = _make_client(captured)
    r = client.post(
        "/v1/containers",
        json={
            "name": "x", "image_variant": "slim",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7", "system_prompt": "",
                       "system_prompt_mode": "augment", "tools": [], "context": {}},
        },
    )
    assert r.status_code == 201, r.text
    assert captured["mem_limit"] == "2g"
    assert captured["cpus"] == 1.0
    assert r.json()["mem_limit"] == "2g"
    assert r.json()["cpus"] == 1.0


def test_create_with_explicit_override() -> None:
    captured: dict = {}
    client = _make_client(captured)
    r = client.post(
        "/v1/containers",
        json={
            "name": "x", "image_variant": "slim",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7", "system_prompt": "",
                       "system_prompt_mode": "augment", "tools": [], "context": {}},
            "resource_limits": {"mem_limit": "3g"},
        },
    )
    assert r.status_code == 201, r.text
    assert captured["mem_limit"] == "3g"
    assert captured["cpus"] == 1.0  # slim default, since cpus wasn't overridden


def test_create_out_of_bounds_override_rejected() -> None:
    captured: dict = {}
    client = _make_client(captured)
    r = client.post(
        "/v1/containers",
        json={
            "name": "x", "image_variant": "slim",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7", "system_prompt": "",
                       "system_prompt_mode": "augment", "tools": [], "context": {}},
            "resource_limits": {"cpus": 99.0},
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["field"] == "resource_limits.cpus"
    assert "mem_limit" not in captured  # rejected before provisioning
