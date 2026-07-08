"""Skills router auth-gating + HTTP-path tests (unit; no DB).

Mirrors test_templates_router_auth.py: FastAPI TestClient + dependency_overrides
with a tiny fake session, so the role gate and the handler branches (validation,
404, 409 conflict, staff-without-tenant) are exercised without a real database.

Role matrix (spec: opencode skills):
    list / get          -> any authenticated principal (member)
    create/patch/delete -> admin/owner (staff get a clean 403, not a 500)

Note: true cross-tenant DB isolation (the `tenant_id == principal.tenant_id`
WHERE predicate) is enforced in SQL and not observable through the fake session;
it shares the same pattern as the templates/credentials routers.
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


class _Row:
    """Mimics a SQLAlchemy Row: exposes ``._mapping`` for dict(row._mapping)."""

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
    """skills.py calls `request.app.state.session_factory()` directly."""

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
OWNER = Principal(tenant_id="ten_1", role="owner", is_staff=False, user_id="usr_o")
API_KEY = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)
STAFF = Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_s")

_BODY = {"name": "git-release", "description": "Make releases"}


# --- create / patch / delete require admin -----------------------------------

def test_member_forbidden_to_create() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/skills", json=_BODY)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_api_key_principal_forbidden_to_create() -> None:
    _use(API_KEY)
    with TestClient(app) as c:
        r = c.post("/v1/skills", json=_BODY)
    assert r.status_code == 403


def test_member_forbidden_to_patch() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.patch("/v1/skills/skl_1", json={"description": "x"})
    assert r.status_code == 403


def test_member_forbidden_to_delete() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.delete("/v1/skills/skl_1")
    assert r.status_code == 403


# --- admin / owner allowed to create -----------------------------------------

def test_admin_creates_skill_and_detail_view_has_body() -> None:
    _use(ADMIN, rows=[])  # dup-check finds nothing
    with TestClient(app) as c:
        r = c.post("/v1/skills", json={"name": "git-release", "description": "Make releases", "body": "# do"})
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "git-release"
    assert j["body"] == "# do"          # create returns the detail view
    assert "tenant_id" not in j


def test_owner_allowed_to_create() -> None:
    _use(OWNER, rows=[])
    with TestClient(app) as c:
        r = c.post("/v1/skills", json=_BODY)
    assert r.status_code == 200


# --- list is member-open and ships no body -----------------------------------

def test_member_can_list_and_list_omits_body() -> None:
    row = _Row({"id": "skl_1", "tenant_id": "ten_1", "name": "git-release",
                "description": "Make releases", "body": "secret-big-body", "enabled": True,
                "created_by": "u", "created_at": "t", "updated_at": "t"})
    _use(MEMBER, rows=[row])
    with TestClient(app) as c:
        r = c.get("/v1/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert skills[0]["name"] == "git-release"
    assert "body" not in skills[0]      # list never ships the body


# --- validation + conflict + not-found + staff edge --------------------------

def test_admin_create_invalid_name_is_400() -> None:
    _use(ADMIN, rows=[])
    with TestClient(app) as c:
        r = c.post("/v1/skills", json={"name": "Bad Name", "description": "d"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "name"


def test_admin_create_duplicate_name_is_409() -> None:
    # dup-check query returns an existing row → conflict.
    _use(ADMIN, rows=[{"id": "skl_existing"}])
    with TestClient(app) as c:
        r = c.post("/v1/skills", json=_BODY)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_admin_patch_missing_is_404() -> None:
    _use(ADMIN, rows=[])
    with TestClient(app) as c:
        r = c.patch("/v1/skills/skl_missing", json={"description": "x"})
    assert r.status_code == 404


def test_admin_delete_missing_is_404() -> None:
    _use(ADMIN, rows=[])
    with TestClient(app) as c:
        r = c.delete("/v1/skills/skl_missing")
    assert r.status_code == 404


def test_get_missing_is_404() -> None:
    _use(MEMBER, rows=[])
    with TestClient(app) as c:
        r = c.get("/v1/skills/skl_missing")
    assert r.status_code == 404


def test_staff_create_returns_clean_403_not_500() -> None:
    # Staff (tenant_id=None) cannot own a tenant skill; clean 403, not a 500.
    _use(STAFF, rows=[])
    with TestClient(app) as c:
        r = c.post("/v1/skills", json=_BODY)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


# --- git-refs (branch picker) ------------------------------------------------

def test_member_forbidden_to_list_git_refs() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-refs", json={"source_url": "https://x/y.git"})
    assert r.status_code == 403


def test_git_refs_missing_url_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-refs", json={})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "source_url"


def test_git_refs_bad_scheme_is_422() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-refs", json={"source_url": "git@github.com:x/y.git"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "source_url"


def test_git_refs_unreachable_is_502(monkeypatch) -> None:
    # An https URL that resolves but fails to clone surfaces as a 502 (not 422).
    def _boom(_url: str, *, private_key: str | None = None) -> Any:
        raise ValueError("git ls-remote failed: repository not found")

    monkeypatch.setattr("control_plane.routers.skills.list_branches", _boom)
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post(
            "/v1/skills/git-refs",
            json={"source_url": "https://example.com/no/such/repo.git"},
        )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "skill_refs_error"


def test_git_refs_ok_returns_branches(monkeypatch) -> None:
    monkeypatch.setattr(
        "control_plane.routers.skills.list_branches",
        lambda _url, *, private_key=None: (["main", "dev"], "main"),
    )
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-refs", json={"source_url": "https://x/y.git"})
    assert r.status_code == 200
    j = r.json()
    assert j == {"ok": True, "branches": ["main", "dev"], "default_branch": "main"}


# --- git-discover (multi-skill repo picker) -----------------------------------

def test_member_forbidden_to_discover() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover",
                   json={"source_url": "https://x/y.git", "source_ref": "main"})
    assert r.status_code == 403


def test_discover_missing_url_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover", json={"source_ref": "main"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "source_url"


def test_discover_missing_ref_is_400() -> None:
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover", json={"source_url": "https://x/y.git"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "source_ref"


def test_discover_bad_scheme_is_422(monkeypatch) -> None:
    def _reject(**_kw: Any) -> Any:
        raise ValueError("source_url must be an https:// git URL")

    monkeypatch.setattr("control_plane.routers.skills.discover_git_skills", _reject)
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover",
                   json={"source_url": "git@github.com:x/y.git", "source_ref": "main"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "source_url"


def test_discover_unknown_ref_is_422_on_ref_field(monkeypatch) -> None:
    def _boom(**_kw: Any) -> Any:
        raise ValueError("ref 'nope' not found in https://x/y.git")

    monkeypatch.setattr("control_plane.routers.skills.discover_git_skills", _boom)
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover",
                   json={"source_url": "https://x/y.git", "source_ref": "nope"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "source_ref"


def test_discover_unreachable_is_502(monkeypatch) -> None:
    def _boom(**_kw: Any) -> Any:
        raise ValueError("git fetch failed: repository not found")

    monkeypatch.setattr("control_plane.routers.skills.discover_git_skills", _boom)
    _use(ADMIN)
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover",
                   json={"source_url": "https://x/y.git", "source_ref": "main"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "skill_discover_error"


def test_discover_ok_flags_installed_names(monkeypatch) -> None:
    from control_plane.skills_fetch import DiscoveredRepo, DiscoveredSkill

    monkeypatch.setattr(
        "control_plane.routers.skills.discover_git_skills",
        lambda **_kw: DiscoveredRepo(
            pinned_sha="a" * 40, truncated=False,
            skills=[
                DiscoveredSkill(subpath="x", name="already-here",
                                description="d1", valid=True, error=None),
                DiscoveredSkill(subpath="y", name="brand-new",
                                description="d2", valid=True, error=None),
                DiscoveredSkill(subpath="z", name="", description="",
                                valid=False, error="SKILL.md missing frontmatter"),
            ],
        ),
    )
    # The installed-names query returns one existing skill name.
    _use(ADMIN, rows=[_Row({"name": "already-here"})])
    with TestClient(app) as c:
        r = c.post("/v1/skills/git-discover",
                   json={"source_url": "https://x/y.git", "source_ref": "main"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["pinned_sha"] == "a" * 40
    assert j["truncated"] is False
    by_subpath = {s["subpath"]: s for s in j["skills"]}
    assert by_subpath["x"]["installed"] is True
    assert by_subpath["y"]["installed"] is False
    assert by_subpath["z"]["installed"] is False
    assert by_subpath["z"]["valid"] is False
