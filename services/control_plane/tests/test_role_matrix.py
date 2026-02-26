"""Role permission matrix — router-level gate integration tests.

Verifies that the gate helpers (require_session_admin, require_staff) enforce
role boundaries at the router level.  FastAPI TestClient + dependency_overrides
are used so no DB is needed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

import control_plane.routers.admin as admin_mod
import control_plane.routers.credentials as cred_mod
import control_plane.routers.users as users_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

# ---------------------------------------------------------------------------
# Minimal settings — no real DB needed because sessions are overridden.
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

app = create_app(_SETTINGS)


class _NullConn:
    """Stub DB connection that returns empty results for any query."""

    async def execute(self, *a: Any, **k: Any) -> _NullResult:
        return _NullResult()


class _NullResult:
    def mappings(self) -> _NullResult:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def scalar_one(self) -> int:
        return 0

    def scalar_one_or_none(self) -> None:
        return None


async def _null_session() -> AsyncIterator[_NullConn]:
    yield _NullConn()


def _inject(principal: Principal) -> None:
    """Wire a fixed Principal + null DB session into the app."""
    app.dependency_overrides[resolve_principal] = lambda: principal
    # Override each router's local _session so no real DB is needed.
    app.dependency_overrides[users_mod._session] = _null_session
    app.dependency_overrides[cred_mod._session] = _null_session
    app.dependency_overrides[admin_mod._session] = _null_session


def teardown_function() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Member is 403 on admin-only routes
# ---------------------------------------------------------------------------


def test_member_forbidden_on_users() -> None:
    _inject(Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_1"))
    with TestClient(app) as c:
        r = c.get("/v1/users")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_member_forbidden_on_credentials() -> None:
    _inject(Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_1"))
    with TestClient(app) as c:
        r = c.get("/v1/credentials")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Admin is allowed on session-admin routes
# ---------------------------------------------------------------------------


def test_admin_allowed_on_users() -> None:
    _inject(Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_2"))
    with TestClient(app) as c:
        r = c.get("/v1/users")
    assert r.status_code == 200


def test_admin_allowed_on_credentials() -> None:
    _inject(Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_2"))
    with TestClient(app) as c:
        r = c.get("/v1/credentials")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# API-key principal (user_id=None) is 403 on session-only routes
# ---------------------------------------------------------------------------


def test_api_key_principal_forbidden_on_users_session_only() -> None:
    # API-key principals: user_id is None and not staff → session-only routes 403.
    _inject(Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None))
    with TestClient(app) as c:
        r = c.get("/v1/users")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Staff-only routes
# ---------------------------------------------------------------------------


def test_non_staff_forbidden_on_admin_tenants() -> None:
    _inject(Principal(tenant_id="ten_1", role="owner", is_staff=False, user_id="usr_3"))
    with TestClient(app) as c:
        r = c.get("/admin/v1/tenants")
    assert r.status_code == 403


def test_staff_allowed_on_admin_tenants() -> None:
    _inject(Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_staff"))
    with TestClient(app) as c:
        r = c.get("/admin/v1/tenants")
    assert r.status_code == 200
