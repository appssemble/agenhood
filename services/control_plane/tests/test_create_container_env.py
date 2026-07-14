from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.containers as containers_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.docker_ctl.provision import ProvisionResult
from control_plane.env_vars import store_env_vars

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
_KEY = os.urandom(32)


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
        self.env_vars = None


class _FakeSession:
    def __init__(self) -> None:
        self._row = _FakeRow("2g", 1.0)  # slim defaults, as resolved by the handler
        self.inserts: list[dict] = []

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        if s.startswith("insert into containers"):
            self.inserts.append(dict(stmt.compile().params))
            return _FakeResult()
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


def _make_client(captured: dict) -> tuple[_FakeSession, TestClient]:
    fake_session = _FakeSession()

    async def _fake_session_dep() -> AsyncIterator[_FakeSession]:
        yield fake_session

    async def fake_provision_container(**kwargs):
        captured.update(kwargs)
        return ProvisionResult(docker_name="agent-x", volume_name="vol-x", shim_token="tok")

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    containers_mod.provision_container = fake_provision_container  # type: ignore[assignment]
    containers_mod.load_key_from_env = lambda: _KEY  # type: ignore[assignment]
    return fake_session, TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


_CONFIG = {"driver": "vanilla", "model": "claude-opus-4-7", "system_prompt": "",
           "system_prompt_mode": "augment", "tools": [], "context": {}}


def test_create_with_inline_env_vars_persists_stored_shape() -> None:
    captured: dict = {}
    session, client = _make_client(captured)
    r = client.post("/v1/containers", json={
        "name": "x", "image_variant": "slim", "config": _CONFIG,
        "env_vars": [{"name": "KEY", "value": "s", "secret": True},
                     {"name": "URL", "value": "https://x"}],
    })
    assert r.status_code == 201, r.text
    stored = session.inserts[0]["env_vars"]
    assert stored[0]["name"] == "KEY" and stored[0]["secret"] is True and "ciphertext" in stored[0]
    assert stored[1] == {"name": "URL", "value": "https://x", "secret": False}


def test_create_secret_without_value_is_400() -> None:
    captured: dict = {}
    _session, client = _make_client(captured)
    r = client.post("/v1/containers", json={
        "name": "x", "image_variant": "slim", "config": _CONFIG,
        "env_vars": [{"name": "KEY", "value": None, "secret": True}],
    })
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "env_vars[0].value"


def test_create_without_env_vars_inserts_none() -> None:
    captured: dict = {}
    session, client = _make_client(captured)
    r = client.post("/v1/containers", json={
        "name": "x", "image_variant": "slim", "config": _CONFIG,
    })
    assert r.status_code == 201, r.text
    assert session.inserts[0]["env_vars"] is None


class _FakeTplRow:
    """Template row with runtime fields; attribute access like a SA row."""

    def __init__(self, env_vars: list | None = None) -> None:
        self.id = "tpl_1"
        self.driver = "vanilla"
        self.model = "claude-opus-4-7"
        self.effort = None
        self.system_prompt = ""
        self.system_prompt_mode = "augment"
        self.tools: list[str] = []
        self.context: dict = {}
        self.skills: list[str] = []
        self.mcp_servers: list[str] = []
        self.image_variant = "slim"
        self.mem_limit = None
        self.cpus = None
        self.env_vars = env_vars


class _FakeSessionWithTemplate(_FakeSession):
    def __init__(self, tpl: _FakeTplRow) -> None:
        super().__init__()
        self._tpl = tpl

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        if "from templates" in s:
            return _FakeResult(value=self._tpl)
        return await super().execute(stmt, params)


def _make_client_with_template(captured: dict, tpl: _FakeTplRow) -> tuple[_FakeSession, TestClient]:
    fake_session = _FakeSessionWithTemplate(tpl)

    async def _fake_session_dep() -> AsyncIterator[_FakeSessionWithTemplate]:
        yield fake_session

    async def fake_provision_container(**kwargs):
        captured.update(kwargs)
        return ProvisionResult(docker_name="agent-x", volume_name="vol-x", shim_token="tok")

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = _fake_session_dep  # type: ignore[attr-defined]
    containers_mod.provision_container = fake_provision_container  # type: ignore[assignment]
    containers_mod.load_key_from_env = lambda: _KEY  # type: ignore[assignment]
    return fake_session, TestClient(_APP, raise_server_exceptions=False)


_TPL_STORED_ENV = store_env_vars(
    [{"name": "SECRET_KEY", "value": "topsecret", "secret": True}], None, lambda: _KEY
)


def test_create_from_template_seeds_env_vars_verbatim() -> None:
    captured: dict = {}
    tpl = _FakeTplRow(env_vars=_TPL_STORED_ENV)
    session, client = _make_client_with_template(captured, tpl)
    r = client.post("/v1/containers", json={"name": "x", "template_id": "tpl_1"})
    assert r.status_code == 201, r.text
    assert session.inserts[0]["env_vars"] == _TPL_STORED_ENV
