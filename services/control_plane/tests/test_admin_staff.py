"""Staff-management admin endpoints: GET /admin/v1/staff and
PATCH /admin/v1/staff/{uid}. No DB — the session dependency is overridden with a
stub conn that returns canned results and records executed statements.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Update

import control_plane.routers.admin as admin_mod
import control_plane.tables as t
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

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

STAFF = Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_admin")


class _Result:
    def __init__(self, mappings_all: Any = None, first: Any = None, rowcount: int = 0) -> None:
        self._m = mappings_all
        self._f = first
        self.rowcount = rowcount

    def mappings(self) -> _Result:
        return self

    def all(self) -> Any:
        return self._m or []

    def first(self) -> Any:
        return self._f


class _StubConn:
    def __init__(self, mappings_all: Any = None, first: Any = None, rowcount: int = 0) -> None:
        self._m = mappings_all
        self._f = first
        self._rowcount = rowcount
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, *a: Any, **k: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._m, self._f, self._rowcount)

    async def commit(self) -> None:
        return None


def _wire(conn: _StubConn, principal: Principal = STAFF) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal

    async def _s() -> AsyncIterator[Any]:
        yield conn

    app.dependency_overrides[admin_mod._session] = _s


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_list_staff_returns_staff_rows() -> None:
    rows = [{
        "id": "usr_1", "email": "a@x.io", "name": "A", "status": "active",
        "must_change_password": True, "created_at": "2026-01-01T00:00:00Z",
    }]
    _wire(_StubConn(mappings_all=rows))
    with TestClient(app) as c:
        r = c.get("/admin/v1/staff")
    assert r.status_code == 200, r.text
    assert r.json()["staff"][0]["email"] == "a@x.io"


def test_cannot_change_own_status() -> None:
    _wire(_StubConn(first=(True,)))
    with TestClient(app) as c:
        r = c.patch("/admin/v1/staff/usr_admin", json={"status": "disabled"})
    assert r.status_code == 400


def test_invalid_status_rejected() -> None:
    _wire(_StubConn(first=(True,)))
    with TestClient(app) as c:
        r = c.patch("/admin/v1/staff/usr_other", json={"status": "bogus"})
    assert r.status_code == 400


def test_patch_nonstaff_404() -> None:
    _wire(_StubConn(first=(False,)))
    with TestClient(app) as c:
        r = c.patch("/admin/v1/staff/usr_other", json={"status": "disabled"})
    assert r.status_code == 404


def test_disable_revokes_sessions() -> None:
    conn = _StubConn(first=(True,))
    _wire(conn)
    with TestClient(app) as c:
        r = c.patch("/admin/v1/staff/usr_other", json={"status": "disabled"})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "usr_other", "status": "disabled"}
    # Disabling a staff user revokes their sessions.
    assert any(isinstance(s, Update) and s.table is t.sessions for s in conn.statements)


def test_delete_tenant_audits_disable_action(monkeypatch: Any) -> None:
    """DELETE /admin/v1/tenants/{tid} records an audit row with action
    'tenant.disable' — not a copy-paste of patch_tenant's 'tenant.update_limits'."""
    captured: dict[str, Any] = {}

    async def _fake_audit(conn: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(admin_mod, "audit", _fake_audit)
    _wire(_StubConn(rowcount=1))
    with TestClient(app) as c:
        r = c.delete("/admin/v1/tenants/ten_x")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "ten_x", "status": "disabled"}
    assert captured["action"] == "tenant.disable"
