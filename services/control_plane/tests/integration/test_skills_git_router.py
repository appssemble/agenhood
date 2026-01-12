"""Integration tests: git-sourced skill creation and refresh via a local repo.

Uses a local file:// git repository so no network is needed.  The fixtures
build a minimal control-plane app (just testcontainers Postgres + alembic) and
authenticate as a freshly bootstrapped owner per test.
"""
from __future__ import annotations

import subprocess
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration]

_ADMIN_HEADERS = {"Authorization": "Bearer boot-test-key"}


# Enable file:// git sources for all tests in this module (Fix 4: production
# disallows file:// — integration tests opt-in via this autouse fixture).
@pytest.fixture(autouse=True)
def _allow_file_sources(monkeypatch):
    monkeypatch.setenv("AGENHOOD_ALLOW_FILE_SKILL_SOURCE", "1")


# ---------------------------------------------------------------------------
# Local git repo helpers (mirrors test_skills_fetch._git / _make_repo)
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def _make_repo(tmp_path) -> tuple[str, str]:
    """Create a local git repo with skills/pdf/SKILL.md; return (url, sha)."""
    import pathlib
    repo = pathlib.Path(str(tmp_path)) / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    skill_dir = repo / "skills" / "pdf"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: pdf\ndescription: "Edit PDFs"\n---\n# Use it\n'
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.sh").write_text("echo hi\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"file://{repo}", sha


def _append_commit(tmp_path) -> str:
    """Add a second commit to the repo (update SKILL.md); return new HEAD sha."""
    import pathlib
    repo = pathlib.Path(str(tmp_path)) / "repo"
    (repo / "skills" / "pdf" / "SKILL.md").write_text(
        '---\nname: pdf\ndescription: "Edit PDFs v2"\n---\n# Updated\n'
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "update skill"], repo)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


# ---------------------------------------------------------------------------
# App fixture — minimal app backed by the migrated testcontainer Postgres
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def skills_app(migrated_db: str):
    """Lightweight control-plane app for skills integration tests.

    Does not require docker_network / agent_image / stub_llm; only the
    testcontainer Postgres (via ``migrated_db``) is needed."""
    from control_plane.app import create_app
    from control_plane.config import Settings
    from control_plane.seed import apply_seed

    settings = Settings(
        database_url=migrated_db,
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seedkey",
        seed_llm_api_key="",
        agent_image_tag="test",
        internal_network="test-net",
        readyz_timeout_seconds=5.0,
        shim_port=8080,
        admin_api_key="boot-test-key",
        session_cookie_secure=False,  # plain HTTP for test client
    )
    app = create_app(settings)
    factory = app.state.session_factory
    async with factory() as s:
        await apply_seed(s, settings)
    yield app
    await app.state.engine.dispose()


# ---------------------------------------------------------------------------
# Owner-authenticated client fixture — fresh tenant per test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def owner_client(skills_app):
    """AsyncClient authenticated as a freshly created owner (unique per test)."""
    email = f"owner-git-{uuid.uuid4().hex[:8]}@skills.example.com"
    password = "pw-skills-test"

    transport = ASGITransport(app=skills_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/admin/v1/tenants",
            headers=_ADMIN_HEADERS,
            json={
                "name": f"SkillsGitTest-{email}",
                "limits": {},
                "owner": {"email": email, "name": "Git Skills Owner", "password": password},
            },
        )
        assert r.status_code == 201, f"tenant bootstrap failed: {r.text}"

        login = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, f"login failed: {login.text}"

        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_create_git_skill_fetches_and_pins(owner_client: AsyncClient, tmp_path) -> None:
    url, sha = _make_repo(tmp_path)
    resp = await owner_client.post(
        "/v1/skills",
        json={
            "source_type": "git",
            "source_url": url,
            "source_subpath": "skills/pdf",
            "source_ref": "main",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "pdf"
    assert body["source_type"] == "git"
    assert body["pinned_sha"] == sha
    assert body["bundle_size"] > 0
    assert "bundle" not in body  # raw bytes must never be returned


async def test_refresh_git_skill_repins(owner_client: AsyncClient, tmp_path) -> None:
    url, sha1 = _make_repo(tmp_path)
    create_resp = await owner_client.post(
        "/v1/skills",
        json={
            "source_type": "git",
            "source_url": url,
            "source_subpath": "skills/pdf",
            "source_ref": "main",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["pinned_sha"] == sha1

    sha2 = _append_commit(tmp_path)
    assert sha2 != sha1

    refreshed = await owner_client.post(f"/v1/skills/{created['id']}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["pinned_sha"] == sha2


async def test_patch_git_skill_enabled_only(owner_client: AsyncClient, tmp_path) -> None:
    """PATCH on a git skill: name/description changes are silently ignored; only
    ``enabled`` may be toggled (Fix 2 — avoid desyncing stored name from bundle)."""
    url, _ = _make_repo(tmp_path)
    create_resp = await owner_client.post(
        "/v1/skills",
        json={
            "source_type": "git",
            "source_url": url,
            "source_subpath": "skills/pdf",
            "source_ref": "main",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["name"] == "pdf"
    assert created["enabled"] is True

    # Attempt to rename — name must remain unchanged; enabled must be toggled.
    patch_resp = await owner_client.patch(
        f"/v1/skills/{created['id']}",
        json={"name": "renamed-skill", "description": "new desc", "enabled": False},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    assert patched["name"] == "pdf"        # rename silently ignored
    assert patched["enabled"] is False     # enabled was toggled
