"""Templates router auth-gating tests (unit; no DB).

Locks in the fix that converted the templates router from a never-set
`app.state.require_principal(...)` call to proper FastAPI dependencies, and the
role matrix from the spec §11 / web-console brief §6.9:

    browse (list/get) + clone  -> any authenticated principal (member)
    create / edit / delete      -> admin/owner (staff get a clean 403, not a 500)

FastAPI TestClient + dependency_overrides are used (mirrors test_role_matrix),
so no real database is required: the role gate runs before the handler body, and
a tiny fake session covers the handlers that do reach a query.
"""
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


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async context-manager session stub; templates.py calls
    `request.app.state.session_factory()` directly (not a _session Depends)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, *a: Any, **k: Any) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:  # no-op
        return None


def _use(principal: Principal, rows: list[Any] | None = None) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal
    app.state.session_factory = lambda: _FakeSession(rows or [])  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


MEMBER = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_m")
ADMIN = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")
OWNER = Principal(tenant_id="ten_1", role="owner", is_staff=False, user_id="usr_o")
API_KEY = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)
STAFF = Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_s")

_BODY = {"name": "T", "driver": "vanilla"}


# --- create / patch / delete require admin (the privilege-escalation fix) -----

def test_member_forbidden_to_create() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_api_key_principal_forbidden_to_create() -> None:
    # A tenant API key is role="member" — must not be able to mint templates.
    _use(API_KEY)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 403


def test_member_forbidden_to_patch() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"name": "x"})
    assert r.status_code == 403


def test_member_forbidden_to_delete() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.delete("/v1/templates/tpl_1")
    assert r.status_code == 403


# --- admin / owner allowed to create ------------------------------------------

def test_admin_allowed_to_create() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 200
    assert r.json()["name"] == "T"
    assert r.json()["is_builtin"] is False


def test_owner_allowed_to_create() -> None:
    _use(OWNER)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 200


def test_create_sets_created_by_to_user_id() -> None:
    # created_by tracks the acting USER (matches prompts.py/workflows.py), not the tenant.
    _use(ADMIN)  # user_id="usr_a", tenant_id="ten_1"
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 200
    assert r.json()["created_by"] == "usr_a"


def test_clone_sets_created_by_to_user_id() -> None:
    class _R:
        _mapping: dict[str, Any] = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "vanilla",
            "model": None, "system_prompt": "", "system_prompt_mode": "augment",
            "tools": [], "context": {}, "skills": [], "mcp_servers": [],
            "limits": {}, "is_builtin": False, "created_by": "usr_src",
        }

    _use(ADMIN, rows=[_R()])  # user_id="usr_a"
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_1/clone", json={"name": "T-clone"})
    assert r.status_code == 200
    assert r.json()["created_by"] == "usr_a"


# --- browse + clone are member-open -------------------------------------------

def test_member_can_list() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/templates")
    assert r.status_code == 200
    assert r.json() == {"templates": []}


def test_member_clone_is_not_role_gated() -> None:
    # Member reaches the clone handler (not 403); with an empty fake DB the
    # source template is absent → 404. The point is: NOT forbidden.
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_missing/clone")
    assert r.status_code == 404


# --- validation + staff edge --------------------------------------------------

def test_admin_create_unknown_driver_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={"name": "T", "driver": "does-not-exist"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "driver"


def test_staff_create_returns_clean_403_not_500() -> None:
    # Staff (tenant_id=None) cannot own a tenant template; must be a clean 403,
    # never an unhandled DB-constraint 500 (the hardening guard).
    _use(STAFF)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_staff_clone_returns_clean_403_not_500() -> None:
    _use(STAFF)
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_any/clone")
    assert r.status_code == 403


def test_admin_create_includes_skills() -> None:
    # A template can carry skills (for codex/opencode); they round-trip in the response.
    _use(ADMIN)
    body = {"name": "T", "driver": "vanilla", "skills": ["skl_1", "skl_2"]}
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=body)
    assert r.status_code == 200
    assert r.json()["skills"] == ["skl_1", "skl_2"]


def test_admin_create_defaults_skills_to_empty() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={"name": "T", "driver": "vanilla"})
    assert r.status_code == 200
    assert r.json()["skills"] == []


# --- mcp_servers round-trip ---------------------------------------------------

def test_admin_create_includes_mcp_servers() -> None:
    # mcp_servers list persists and round-trips in the create response.
    _use(ADMIN)
    body = {"name": "T", "driver": "vanilla", "mcp_servers": ["mcp_1", "mcp_2"]}
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=body)
    assert r.status_code == 200
    assert r.json()["mcp_servers"] == ["mcp_1", "mcp_2"]


def test_admin_create_defaults_mcp_servers_to_empty() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={"name": "T", "driver": "vanilla"})
    assert r.status_code == 200
    assert r.json()["mcp_servers"] == []


def test_admin_patch_updates_mcp_servers() -> None:
    # PATCH with mcp_servers updates the template and returns the new value.
    class _R:
        _mapping: dict[str, Any] = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "vanilla",
            "model": None, "system_prompt": "", "system_prompt_mode": "augment",
            "tools": [], "context": {}, "skills": [], "mcp_servers": [],
            "limits": {}, "is_builtin": False, "created_by": "ten_1",
        }

    _use(ADMIN, rows=[_R()])
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"mcp_servers": ["mcp_1"]})
    assert r.status_code == 200
    assert r.json()["mcp_servers"] == ["mcp_1"]


def test_clone_copies_mcp_servers() -> None:
    # Cloning a template copies its mcp_servers into the new row.
    class _R:
        _mapping: dict[str, Any] = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "vanilla",
            "model": "claude-sonnet-4-6", "system_prompt": "", "system_prompt_mode": "augment",
            "tools": [], "context": {}, "skills": [], "mcp_servers": ["mcp_1"],
            "limits": {}, "is_builtin": False, "created_by": "ten_1",
        }

    _use(ADMIN, rows=[_R()])
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_1/clone", json={"name": "T-clone"})
    assert r.status_code == 200
    assert r.json()["mcp_servers"] == ["mcp_1"]


# --- context normalization ----------------------------------------------------
# Rows written before normalization (built-ins seeded with {}, old clones, raw
# API creates) may hold a sparse or malformed context. The API must always
# return the full ContextSpec shape and never 500 on legacy data.

_FULL_CTX: dict[str, Any] = {"variables": {}, "text": None, "files": []}


def _ctx_row(context: Any) -> Any:
    class _R:
        _mapping: dict[str, Any] = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "vanilla",
            "model": None, "system_prompt": "", "system_prompt_mode": "augment",
            "tools": [], "context": context, "skills": [], "mcp_servers": [],
            "limits": {}, "is_builtin": False, "created_by": "u",
        }
    return _R()


def test_create_without_context_returns_full_shape() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 200
    assert r.json()["context"] == _FULL_CTX


def test_create_with_partial_context_fills_shape() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "context": {"variables": {"a": "b"}}})
    assert r.status_code == 200
    assert r.json()["context"] == {"variables": {"a": "b"}, "text": None, "files": []}


def test_create_with_malformed_context_is_400() -> None:
    # Non-string variable values would fail container creation later — reject
    # them at the door instead of storing unusable data.
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "context": {"variables": {"n": 5}}})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "context"


def test_get_returns_full_context_for_sparse_row() -> None:
    _use(MEMBER, rows=[_ctx_row({})])
    with TestClient(app) as c:
        r = c.get("/v1/templates/tpl_1")
    assert r.status_code == 200
    assert r.json()["context"] == _FULL_CTX


def test_list_survives_a_malformed_legacy_context_row() -> None:
    # One bad legacy row must degrade to defaults, not 500 the whole listing.
    _use(MEMBER, rows=[_ctx_row({"variables": {"n": 5}})])
    with TestClient(app) as c:
        r = c.get("/v1/templates")
    assert r.status_code == 200
    assert r.json()["templates"][0]["context"] == _FULL_CTX


def test_patch_normalizes_partial_context() -> None:
    _use(ADMIN, rows=[_ctx_row({})])
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"context": {"text": "Be terse."}})
    assert r.status_code == 200
    assert r.json()["context"] == {"variables": {}, "text": "Be terse.", "files": []}


def test_patch_with_malformed_context_is_400() -> None:
    _use(ADMIN, rows=[_ctx_row({})])
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"context": {"files": "not-a-list"}})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "context"


def test_clone_normalizes_sparse_source_context() -> None:
    # Cloning a built-in (context {}) must produce a full-shape clone, leniently
    # (legacy junk in the source degrades to defaults rather than failing).
    _use(ADMIN, rows=[_ctx_row({})])
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_1/clone", json={"name": "T-clone"})
    assert r.status_code == 200
    assert r.json()["context"] == _FULL_CTX


# --- template runtime resources (image_variant / mem_limit / cpus) ------------

def _rt_row(**over: Any) -> Any:
    class _R:
        _mapping: dict[str, Any] = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "vanilla",
            "model": None, "system_prompt": "", "system_prompt_mode": "augment",
            "tools": [], "context": {}, "skills": [], "mcp_servers": [],
            "limits": {}, "is_builtin": False, "created_by": "u",
            "image_variant": None, "mem_limit": None, "cpus": None,
            **over,
        }
    return _R()


def test_create_accepts_and_returns_runtime_fields() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={
            **_BODY, "image_variant": "slim", "mem_limit": "512m", "cpus": 1,
        })
    assert r.status_code == 200
    j = r.json()
    assert j["image_variant"] == "slim"
    assert j["mem_limit"] == "512m"
    assert j["cpus"] == 1.0


def test_create_without_runtime_fields_returns_nulls() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json=_BODY)
    assert r.status_code == 200
    j = r.json()
    assert j["image_variant"] is None
    assert j["mem_limit"] is None
    assert j["cpus"] is None


def test_create_unknown_variant_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "image_variant": "mega"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "image_variant"


def test_create_out_of_bounds_mem_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "mem_limit": "64g"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "mem_limit"


def test_create_out_of_bounds_cpus_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "cpus": 64})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "cpus"


def test_create_non_numeric_cpus_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={**_BODY, "cpus": True})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "cpus"


def test_create_slim_with_chromium_tool_is_409() -> None:
    # web_fetch requires the chromium feature, which slim does not provide.
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/templates", json={
            **_BODY, "image_variant": "slim", "tools": ["web_fetch"],
        })
    assert r.status_code == 409


def test_patch_tools_regates_against_stored_slim_variant() -> None:
    # Template already pinned to slim; adding a chromium tool must 409.
    _use(ADMIN, rows=[_rt_row(image_variant="slim")])
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"tools": ["web_fetch"]})
    assert r.status_code == 409


def test_patch_sets_and_clears_runtime_fields() -> None:
    _use(ADMIN, rows=[_rt_row(mem_limit="1g")])
    with TestClient(app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"mem_limit": None, "cpus": 2})
    assert r.status_code == 200
    assert r.json()["mem_limit"] is None
    assert r.json()["cpus"] == 2.0


def test_clone_copies_runtime_fields() -> None:
    _use(ADMIN, rows=[_rt_row(image_variant="slim", mem_limit="512m", cpus=0.5)])
    with TestClient(app) as c:
        r = c.post("/v1/templates/tpl_1/clone", json={"name": "T-clone"})
    assert r.status_code == 200
    j = r.json()
    assert j["image_variant"] == "slim"
    assert j["mem_limit"] == "512m"
    assert j["cpus"] == 0.5
