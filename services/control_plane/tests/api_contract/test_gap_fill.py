"""Gap-fill contract tests for audit-RED routes (Unit C, Task 5).

Each test addresses a confirmed-uncovered route from AUDIT.md §5 (21 RED routes).
Tests go BEYOND the 401-gate (already covered by test_route_inventory.py /
test_error_envelope.py) to assert REAL route behaviour when the gate passes:
the correct status code + response shape for the first behavioural boundary
(business logic or DB-ownership check).

Patterns used
-------------
Admin routes (require_staff + admin_mod._session Depends):
    Explicit admin_mod._session override + P_STAFF principal inject.

Container-scoped routes (_principal + containers._session Depends):
    null_session_overrides() + P_ADMIN principal inject.
    _load_owned_container hits null session → first()=None → 404.
    This proves: (a) auth gate passes, (b) DB ownership filter is active.

Scheduled-tasks / workflows (resolve_principal + session_factory direct):
    app.state.session_factory = lambda: _FakeSession().
    Null results trigger the not-found path inside the handlers.

API-keys / credentials (require_session_admin + module-local _session):
    Explicit api_keys_mod._session / cred_mod._session override + P_ADMIN.

Each test can FAIL for a real reason; no tautologies.

False-positive audit notes
--------------------------
None found.  All 21 routes confirmed uncovered by grep before writing.

Integration-tier notes
----------------------
Container routes that require the shim for their HAPPY PATH (git/push,
git/rollback, git/link/verify, git/remote/verify) are tested here at
the DB-boundary only (container not found → 404). Their shim-interaction
happy path belongs in the integration tier.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.admin as admin_mod
import control_plane.routers.api_keys as api_keys_mod
import control_plane.routers.credentials as cred_mod
from control_plane.auth.principal import resolve_principal
from tests.api_contract import contracts as C
from tests.api_contract.gate_helpers import null_session_overrides

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared principals
# ---------------------------------------------------------------------------
P_STAFF = C.P_STAFF   # is_staff=True, tenant_id=None  (for require_staff routes)
P_ADMIN = C.P_ADMIN   # role=admin, tenant_id=ten_1, user_id=usr_a

# ---------------------------------------------------------------------------
# Stub result / connection classes
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stub SQLAlchemy result with rowcount and mappings() support."""

    def __init__(self, rows: list[Any] = (), rowcount: int = 0) -> None:
        self._rows = list(rows)
        self.rowcount = rowcount

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeMappings:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


# ---------------------------------------------------------------------------
# Null connection (no rowcount needed; compatible with gate_helpers pattern)
# ---------------------------------------------------------------------------


class _NullConn:
    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        return _FakeResult()

    async def commit(self) -> None:
        pass


async def _null_session_gen() -> AsyncIterator[_NullConn]:
    """Drop-in null session for any router's local _session Depends."""
    yield _NullConn()


# ---------------------------------------------------------------------------
# Admin-route fakes
# ---------------------------------------------------------------------------


class _RowcountOneConn:
    """Every execute() returns rowcount=1 (simulates found/affected row)."""

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        return _FakeResult(rowcount=1)

    async def commit(self) -> None:
        pass


async def _admin_session_rowcount_one() -> AsyncIterator[_RowcountOneConn]:
    yield _RowcountOneConn()


class _TenantFoundConn:
    """Returns a fake tenant dict on the FIRST SELECT; empty _FakeResult after."""

    def __init__(self) -> None:
        self._calls = 0

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        self._calls += 1
        if self._calls == 1:
            # Simulates SELECT on tenants table — handler calls .mappings().first()
            return _FakeResult(
                rows=[{"id": "t_x", "name": "T", "limits": {}, "status": "active"}]
            )
        # Subsequent calls: UPDATE, audit INSERT, etc. — no meaningful return needed.
        return _FakeResult(rowcount=1)

    async def commit(self) -> None:
        pass


async def _admin_session_tenant_found() -> AsyncIterator[_TenantFoundConn]:
    yield _TenantFoundConn()


# ---------------------------------------------------------------------------
# Fake session for routers that use request.app.state.session_factory directly
# (scheduled-tasks, workflows — they do NOT use Depends(_session))
# ---------------------------------------------------------------------------


class _FakeSession:
    """Async context-manager session returning scripted _FakeResults in order."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = list(results or [])
        self._idx = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        if self._idx < len(self._results):
            r = self._results[self._idx]
            self._idx += 1
            return _FakeResult(rows=[r] if r is not None else [])
        return _FakeResult()

    async def commit(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Module-level app + helpers
# ---------------------------------------------------------------------------
_app = C.make_app()
_null_overrides = null_session_overrides(_app)
_orig_sf = _app.state.session_factory  # preserved for teardown


def teardown_function() -> None:
    _app.dependency_overrides.clear()
    _app.state.session_factory = _orig_sf  # restore original to avoid cross-test bleed


def _inject(principal: Any) -> None:
    """Wire a principal + null sessions for container-scoped routes."""
    _app.dependency_overrides[resolve_principal] = lambda: principal
    _app.dependency_overrides.update(_null_overrides)


def _use_sf(principal: Any, session_factory: Any) -> None:
    """Wire principal + session_factory for routers that don't use Depends(_session)."""
    _app.dependency_overrides[resolve_principal] = lambda: principal
    _app.state.session_factory = session_factory


# ===========================================================================
# Route 1: GET /admin/v1/health
# ===========================================================================


def test_admin_health_staff_ok() -> None:
    """GET /admin/v1/health — staff principal + null session → 200 with health counters."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.get("/admin/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # All three counters must be present (scalar_one → 0 from null session).
    assert "tenants" in body
    assert "running_containers" in body
    assert "active_tasks" in body


# ===========================================================================
# Route 2 & 3: POST /admin/v1/staff
# ===========================================================================


def test_admin_staff_create_validation_422() -> None:
    """POST /admin/v1/staff with empty body → 422 (email, name, password required)."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/admin/v1/staff", json={})
    assert r.status_code == 422


def test_admin_staff_create_ok() -> None:
    """POST /admin/v1/staff with valid body → 201, is_staff=True in response."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post(
            "/admin/v1/staff",
            json={"email": "newstaff@example.com", "name": "New Staff", "password": "s3cr3t!"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["is_staff"] is True
    assert "id" in body


# ===========================================================================
# Route 4: DELETE /admin/v1/tenants/{tid}
# ===========================================================================


def test_admin_delete_tenant_ok() -> None:
    """DELETE /admin/v1/tenants/{tid} — found tenant (rowcount=1) → 200, status=disabled."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _admin_session_rowcount_one
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.delete("/admin/v1/tenants/t_x")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "t_x"
    assert body["status"] == "disabled"


# ===========================================================================
# Routes 5 & 6: PATCH /admin/v1/tenants/{tid}
# ===========================================================================


def test_admin_patch_tenant_not_found() -> None:
    """PATCH /admin/v1/tenants/{tid} — tenant absent in null session → 404 not_found."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.patch("/admin/v1/tenants/t_missing", json={"name": "X"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_admin_patch_tenant_invalid_status() -> None:
    """PATCH /admin/v1/tenants/{tid} — found tenant, bad status value → 400 validation_error."""
    _app.dependency_overrides[resolve_principal] = lambda: P_STAFF
    _app.dependency_overrides[admin_mod._session] = _admin_session_tenant_found
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.patch("/admin/v1/tenants/t_x", json={"status": "completely_invalid"})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["field"] == "status"


# ===========================================================================
# Container-scoped routes: gate passes, unknown container → 404
#
# All routes below use Depends(_principal) + Depends(containers._session).
# null_session_overrides() overrides containers._session → null conn.
# _load_owned_container / _require_running hits null session →
#   .first() = None → not_found("container … not found") → 404.
# This proves the auth gate passes and the DB ownership filter activates.
# ===========================================================================


# Route 7: PUT /v1/containers/{cid}/files/raw
def test_files_upload_container_not_found() -> None:
    """PUT /containers/{cid}/files/raw — gate passes, unknown container → 404 not_found."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.put("/v1/containers/c_x/files/raw?path=readme.md", content=b"hello")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 8: POST /v1/containers/{cid}/git/link/verify
def test_git_link_verify_container_not_found() -> None:
    """POST /containers/{cid}/git/link/verify — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post(
            "/v1/containers/c_x/git/link/verify",
            json={"url": "git@github.com:org/repo.git"},
        )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 9: POST /v1/containers/{cid}/git/push
def test_git_push_container_not_found() -> None:
    """POST /containers/{cid}/git/push — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/v1/containers/c_x/git/push")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 10: DELETE /v1/containers/{cid}/git/remote
def test_git_remote_delete_container_not_found() -> None:
    """DELETE /containers/{cid}/git/remote — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.delete("/v1/containers/c_x/git/remote")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 11: POST /v1/containers/{cid}/git/remote/key
def test_git_remote_key_container_not_found() -> None:
    """POST /containers/{cid}/git/remote/key — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/v1/containers/c_x/git/remote/key")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 12: POST /v1/containers/{cid}/git/remote/verify
def test_git_remote_verify_container_not_found() -> None:
    """POST /containers/{cid}/git/remote/verify — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post(
            "/v1/containers/c_x/git/remote/verify",
            json={"url": "git@github.com:org/repo.git"},
        )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 13: POST /v1/containers/{cid}/git/rollback (two tests)
def test_git_rollback_missing_sha_422() -> None:
    """POST /containers/{cid}/git/rollback with empty body → 422 (sha is required)."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/v1/containers/c_x/git/rollback", json={})
    assert r.status_code == 422


def test_git_rollback_container_not_found() -> None:
    """POST /containers/{cid}/git/rollback — sha provided, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/v1/containers/c_x/git/rollback", json={"sha": "abc1234"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 14: POST /v1/containers/{cid}/tasks/{tid}/cancel
def test_task_cancel_container_not_found() -> None:
    """POST /containers/{cid}/tasks/{tid}/cancel — gate passes, unknown container → 404."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.post("/v1/containers/c_x/tasks/t_x/cancel")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 15: GET /v1/tasks
def test_tenant_tasks_list_empty() -> None:
    """GET /v1/tasks — authenticated, no tasks in null session → 200 {"tasks": []}."""
    _inject(P_ADMIN)
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.get("/v1/tasks")
    assert r.status_code == 200
    body = r.json()
    assert "tasks" in body
    assert body["tasks"] == []


# ===========================================================================
# Scheduled-tasks routes
# (resolve_principal Depends + request.app.state.session_factory direct call)
# ===========================================================================


# Route 16: GET /v1/scheduled-tasks
def test_scheduled_tasks_list_empty() -> None:
    """GET /v1/scheduled-tasks — authenticated, empty session → 200 {"scheduled_tasks": []}."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.get("/v1/scheduled-tasks")
    assert r.status_code == 200
    body = r.json()
    assert "scheduled_tasks" in body
    assert body["scheduled_tasks"] == []


# Route 17: DELETE /v1/scheduled-tasks/{sid}
def test_scheduled_task_delete_not_found() -> None:
    """DELETE /v1/scheduled-tasks/{sid} — schedule not found → 404 not_found."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.delete("/v1/scheduled-tasks/s_x")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 18: GET /v1/scheduled-tasks/{sid}
def test_scheduled_task_get_not_found() -> None:
    """GET /v1/scheduled-tasks/{sid} — schedule not found → 404 not_found."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.get("/v1/scheduled-tasks/s_x")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 19: PATCH /v1/scheduled-tasks/{sid}
def test_scheduled_task_patch_not_found() -> None:
    """PATCH /v1/scheduled-tasks/{sid} with valid empty patch — not found → 404."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.patch("/v1/scheduled-tasks/s_x", json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ===========================================================================
# Workflows routes
# (resolve_principal Depends + request.app.state.session_factory direct call)
# ===========================================================================


# Route 20: DELETE /v1/workflows/{wid}
def test_workflow_delete_not_found() -> None:
    """DELETE /v1/workflows/{wid} — workflow not found → 404 not_found."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.delete("/v1/workflows/w_x")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Route 21: PATCH /v1/workflows/{wid}
def test_workflow_patch_not_found() -> None:
    """PATCH /v1/workflows/{wid} with empty patch body — workflow not found → 404."""
    _use_sf(P_ADMIN, lambda: _FakeSession())
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.patch("/v1/workflows/w_x", json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ===========================================================================
# Route 22: DELETE /v1/api-keys/{kid}
# (require_session_admin + api_keys_mod._session Depends — NOT in null_overrides)
# ===========================================================================


def test_api_key_delete_not_found() -> None:
    """DELETE /v1/api-keys/{kid} — key absent in null session → 404 not_found."""
    _app.dependency_overrides[resolve_principal] = lambda: P_ADMIN
    _app.dependency_overrides[api_keys_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.delete("/v1/api-keys/key_x")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ===========================================================================
# Route 23: GET /v1/credentials/oauth/openai/connections/{connection_id}/events
# (require_session_admin + cred_mod._session Depends)
# ===========================================================================


def test_openai_oauth_events_connection_not_found() -> None:
    """GET credentials/oauth/openai/connections/{id}/events — connection absent → 404."""
    _app.dependency_overrides[resolve_principal] = lambda: P_ADMIN
    _app.dependency_overrides[cred_mod._session] = _null_session_gen
    with TestClient(_app, raise_server_exceptions=False) as c:
        r = c.get("/v1/credentials/oauth/openai/connections/conn_x/events")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
