"""API-keys list for staff sessions (unit; no DB).

Locks in the fix for the console's always-empty key list: an impersonating
staff session (active tenant selected → tenant_id set, acts as owner per
principal.py) must be able to list that tenant's keys, matching the create
and revoke endpoints in the same router. Staff with NO active tenant still
get a clean 400 (there is no tenant to list for).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.routers.api_keys import _session

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

app = create_app(_SETTINGS)

_ROW = {
    "id": "key_1", "tenant_id": "ten_1", "name": "ci", "key_hash": "h",
    "key_prefix": "tk_live_", "created_by": "usr_o", "last_used_at": None,
    "status": "active", "revoked_at": None, "created_at": "2026-07-14T00:00:00Z",
}


class _FakeMappings:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        return None


def _use(principal: Principal, rows: list[Any] | None = None) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal
    app.dependency_overrides[_session] = lambda: _FakeSession(rows or [])


def teardown_function() -> None:
    app.dependency_overrides.clear()


IMPERSONATING_STAFF = Principal(
    tenant_id="ten_1", role="owner", is_staff=True, user_id="usr_s"
)
CROSS_TENANT_STAFF = Principal(
    tenant_id=None, role="member", is_staff=True, user_id="usr_s"
)


def test_impersonating_staff_lists_the_active_tenants_keys() -> None:
    _use(IMPERSONATING_STAFF, rows=[_ROW])
    r = TestClient(app).get("/v1/api-keys")
    assert r.status_code == 200, r.text
    keys = r.json()["keys"]
    assert [k["id"] for k in keys] == ["key_1"]
    assert "key_hash" not in keys[0]


def test_staff_without_active_tenant_gets_a_clean_400() -> None:
    _use(CROSS_TENANT_STAFF)
    r = TestClient(app).get("/v1/api-keys")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "validation_error"
