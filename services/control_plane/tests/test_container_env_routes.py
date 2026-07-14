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
CONTAINER_ID = "ctr_env_1"
_PRINCIPAL = Principal(tenant_id=TENANT_ID, role="member", is_staff=False, user_id="usr_1")
_KEY = os.urandom(32)


class _FakeResult:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeRow:
    def __init__(self, env_vars: list[dict] | None) -> None:
        self.id = CONTAINER_ID
        self.env_vars = env_vars


class _FakeSession:
    """Serves _load_owned_container and records containers.update() values."""

    def __init__(self, env_vars: list[dict] | None) -> None:
        self.row = _FakeRow(env_vars)
        self.updates: list[dict] = []

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        s = str(stmt).lower()
        if s.startswith("update containers"):
            self.updates.append(dict(stmt.compile().params))
            return _FakeResult()
        if s.startswith("insert into audit_log"):
            return _FakeResult()
        return _FakeResult(value=self.row)

    async def commit(self) -> None:
        pass


def _make_client(session: _FakeSession) -> TestClient:
    async def _dep() -> AsyncIterator[_FakeSession]:
        yield session

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = _dep  # type: ignore[attr-defined]
    containers_mod.load_key_from_env = lambda: _KEY  # type: ignore[assignment]
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


def test_get_env_empty_when_column_null() -> None:
    client = _make_client(_FakeSession(env_vars=None))
    r = client.get(f"/v1/containers/{CONTAINER_ID}/env")
    assert r.status_code == 200
    assert r.json() == []


def test_get_env_masks_secrets() -> None:
    stored = store_env_vars(
        [{"name": "URL", "value": "https://x", "secret": False},
         {"name": "KEY", "value": "s", "secret": True}],
        None, lambda: _KEY,
    )
    client = _make_client(_FakeSession(env_vars=stored))
    r = client.get(f"/v1/containers/{CONTAINER_ID}/env")
    assert r.json() == [
        {"name": "URL", "value": "https://x", "secret": False},
        {"name": "KEY", "value": None, "secret": True},
    ]


def test_put_env_persists_and_returns_masked() -> None:
    session = _FakeSession(env_vars=None)
    client = _make_client(session)
    r = client.put(
        f"/v1/containers/{CONTAINER_ID}/env",
        json=[{"name": "KEY", "value": "s3cret", "secret": True},
              {"name": "URL", "value": "https://x"}],
    )
    assert r.status_code == 200
    assert r.json() == [
        {"name": "KEY", "value": None, "secret": True},
        {"name": "URL", "value": "https://x", "secret": False},
    ]
    assert len(session.updates) == 1
    persisted = session.updates[0]["env_vars"]
    assert persisted[0]["secret"] is True and "ciphertext" in persisted[0]
    assert persisted[1] == {"name": "URL", "value": "https://x", "secret": False}


def test_put_env_secret_null_keeps_existing() -> None:
    existing = store_env_vars(
        [{"name": "KEY", "value": "old", "secret": True}], None, lambda: _KEY
    )
    session = _FakeSession(env_vars=existing)
    client = _make_client(session)
    r = client.put(
        f"/v1/containers/{CONTAINER_ID}/env",
        json=[{"name": "KEY", "value": None, "secret": True}],
    )
    assert r.status_code == 200
    assert session.updates[0]["env_vars"][0]["ciphertext"] == existing[0]["ciphertext"]


def test_put_env_reserved_name_400() -> None:
    client = _make_client(_FakeSession(env_vars=None))
    r = client.put(
        f"/v1/containers/{CONTAINER_ID}/env",
        json=[{"name": "SHIM_TOKEN", "value": "x"}],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["field"] == "env_vars[0].name"
