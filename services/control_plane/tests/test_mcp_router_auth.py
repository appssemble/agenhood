"""MCP router auth-gating + HTTP-path tests (unit; no DB). Mirrors
test_skills_router_auth.py: TestClient + dependency_overrides + a fake session.
Create uses auth_type 'none' so no CREDENTIAL_ENCRYPTION_KEY is needed."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

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
app = create_app(_SETTINGS)


class _Row:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        return None


def _use(principal: Principal, rows: list[Any] | None = None) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal
    app.state.session_factory = lambda: _FakeSession(rows or [])  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


MEMBER = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_m")
ADMIN = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")
_BODY = {"name": "linear", "description": "Linear MCP", "url": "https://mcp.linear.app/mcp"}


def test_member_forbidden_to_create() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/mcp-servers", json=_BODY)
    assert r.status_code == 403


def test_admin_creates_and_view_hides_secret() -> None:
    _use(ADMIN, rows=[])  # dup-check finds nothing
    with TestClient(app) as c:
        r = c.post("/v1/mcp-servers", json=_BODY)
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "linear"
    assert j["secret_set"] is False
    assert "secret_ciphertext" not in j
    assert "tenant_id" not in j


def test_member_can_list_and_secret_never_shipped() -> None:
    row = _Row({"id": "mcp_1", "tenant_id": "ten_1", "name": "linear",
                "description": "d", "url": "https://m", "auth_type": "bearer",
                "auth_header_name": None, "secret_ciphertext": b"ciphertext",
                "enabled": True, "created_by": "u", "created_at": "t", "updated_at": "t"})
    _use(MEMBER, rows=[row])
    with TestClient(app) as c:
        r = c.get("/v1/mcp-servers")
    assert r.status_code == 200
    servers = r.json()["mcp_servers"]
    assert servers[0]["secret_set"] is True
    assert "secret_ciphertext" not in servers[0]


def test_create_rejects_http_url() -> None:
    _use(ADMIN, rows=[])
    with TestClient(app) as c:
        r = c.post("/v1/mcp-servers", json={"name": "x", "description": "d", "url": "http://m"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "url"


# --- member-forbidden for mutating ops (T9-M4 gap) ----------------------------

def test_member_forbidden_to_patch() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.patch("/v1/mcp-servers/mcp_1", json={"description": "updated"})
    assert r.status_code == 403


def test_member_forbidden_to_delete() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.delete("/v1/mcp-servers/mcp_1")
    assert r.status_code == 403


# --- 404 on missing id ---------------------------------------------------------

def test_get_missing_id_returns_404() -> None:
    _use(ADMIN, rows=[])  # empty result → not found
    with TestClient(app) as c:
        r = c.get("/v1/mcp-servers/mcp_missing")
    assert r.status_code == 404


def test_patch_missing_id_returns_404() -> None:
    _use(ADMIN, rows=[])  # empty result → not found (checked before patch logic)
    with TestClient(app) as c:
        r = c.patch("/v1/mcp-servers/mcp_missing", json={})
    assert r.status_code == 404


def test_delete_missing_id_returns_404() -> None:
    _use(ADMIN, rows=[])  # empty result → not found
    with TestClient(app) as c:
        r = c.delete("/v1/mcp-servers/mcp_missing")
    assert r.status_code == 404
