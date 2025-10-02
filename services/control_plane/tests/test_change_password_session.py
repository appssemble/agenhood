"""A self password-change must keep the caller's CURRENT session alive and revoke
only the user's OTHER sessions — otherwise a forced first-login password change
logs the user straight back out (every subsequent call 401s). An admin resetting
*another* user's password still revokes all of that user's sessions.

No DB: we override the session dependency with a conn that records every executed
statement, then inspect the sessions UPDATE's WHERE clause.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Update

import control_plane.routers.users as users_mod
import control_plane.tables as t
from control_plane.app import create_app
from control_plane.auth.passwords import hash_password
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


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._row


class _CaptureConn:
    """Records every executed statement; returns ``user_row`` for the SELECT."""

    def __init__(self, user_row: dict) -> None:  # type: ignore[type-arg]
        self._user_row = user_row
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, *a: Any, **k: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._user_row)

    async def commit(self) -> None:
        return None


def _sessions_update_sql(conn: _CaptureConn) -> str:
    updates = [s for s in conn.statements if isinstance(s, Update) and s.table is t.sessions]
    assert len(updates) == 1, f"expected exactly one sessions UPDATE, got {len(updates)}"
    return str(updates[0])


def _wire(principal: Principal, conn: _CaptureConn) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal

    async def _sess() -> AsyncIterator[_CaptureConn]:
        yield conn

    app.dependency_overrides[users_mod._session] = _sess


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_self_change_keeps_current_session() -> None:
    uid = "usr_self"
    conn = _CaptureConn({"id": uid, "password_hash": hash_password("oldpw")})
    _wire(Principal(tenant_id=None, role="member", is_staff=False, user_id=uid), conn)

    with TestClient(app) as c:
        c.cookies.set("agent_session", "current-token")
        r = c.post(
            f"/v1/users/{uid}/password",
            json={"current_password": "oldpw", "new_password": "newpw-123"},
        )

    assert r.status_code == 200, r.text
    # The revoke must exclude the caller's current session.
    assert "token_hash" in _sessions_update_sql(conn)


def test_admin_reset_other_revokes_all_sessions() -> None:
    target = "usr_other"
    conn = _CaptureConn({"id": target, "password_hash": hash_password("whatever")})
    _wire(Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_admin"), conn)

    with TestClient(app) as c:
        c.cookies.set("agent_session", "admin-token")
        r = c.post(f"/v1/users/{target}/password", json={"new_password": "newpw-123"})

    assert r.status_code == 200, r.text
    # Resetting another user's password revokes ALL their sessions (no exclusion).
    assert "token_hash" not in _sessions_update_sql(conn)
