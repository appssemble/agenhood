"""Route-level tests for the control-plane ``/v1/deploy-keys`` endpoints.

Exercises the real handlers end-to-end against a migrated Postgres
(``db_session`` fixture — skips when docker is unavailable), driving the
router via an ASGI app with ``resolve_principal`` overridden to an admin
``Principal`` for a seeded tenant. Mirrors the fixture approach of
``test_git_link_routes.py``.
"""
from __future__ import annotations

import base64
import os
import uuid
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# A valid base64 32-byte master key so load_key_from_env() works for keygen +
# secret encryption. Set before importing anything that reads it at call time.
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", base64.b64encode(b"A" * 32).decode())

from analytics_seed import insert_tenant  # noqa: E402

from control_plane.app import create_app  # noqa: E402
from control_plane.auth.principal import Principal, resolve_principal  # noqa: E402
from control_plane.config import Settings  # noqa: E402
from control_plane.models_db import skills  # noqa: E402

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


def _make_app(session: AsyncSession, tenant_id: str) -> Any:
    factory = async_sessionmaker(session.bind, expire_on_commit=False, class_=AsyncSession)
    app = create_app(_SETTINGS)
    app.state.session_factory = factory
    app.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id=tenant_id, role="admin", is_staff=False, user_id="usr_1"
    )
    return app


async def _client_for(session: AsyncSession, tenant_id: str):
    app = _make_app(session, tenant_id)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def tenant_id(db_session: AsyncSession) -> str:
    tid = f"dk_ten_{uuid.uuid4().hex[:8]}"
    await insert_tenant(db_session, tid)
    return tid


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, tenant_id: str):
    async for c in _client_for(db_session, tenant_id):
        yield c


@pytest_asyncio.fixture
async def other_tenant_client(db_session: AsyncSession):
    other_tid = f"dk_other_{uuid.uuid4().hex[:8]}"
    await insert_tenant(db_session, other_tid)
    async for c in _client_for(db_session, other_tid):
        yield c


async def _insert_skill_using_key(
    session: AsyncSession, *, tenant_id: str, deploy_key_id: str, name: str = "git-skill"
) -> None:
    """Seed a minimal skill row that references a deploy key, mirroring how
    test_git_link_routes.py seeds rows directly via SQL."""
    await session.execute(
        sa.insert(skills).values(
            id=f"skl_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            name=name,
            description="",
            source_type="git",
            deploy_key_id=deploy_key_id,
        )
    )
    await session.commit()


async def test_create_returns_public_half_only(client: AsyncClient) -> None:
    r = await client.post("/v1/deploy-keys", json={"name": "team-skills"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ssh_public_key"].startswith("ssh-ed25519 ")
    assert "private" not in r.text.lower() and "ciphertext" not in r.text.lower()


async def test_create_duplicate_name_conflicts(client: AsyncClient) -> None:
    await client.post("/v1/deploy-keys", json={"name": "dup"})
    r = await client.post("/v1/deploy-keys", json={"name": "dup"})
    assert r.status_code == 409, r.text


async def test_list_is_tenant_scoped(
    client: AsyncClient, other_tenant_client: AsyncClient
) -> None:
    await client.post("/v1/deploy-keys", json={"name": "mine"})
    r = await other_tenant_client.get("/v1/deploy-keys")
    assert r.status_code == 200, r.text
    assert all(k["name"] != "mine" for k in r.json()["deploy_keys"])


async def test_delete_unused_ok(client: AsyncClient) -> None:
    kid = (await client.post("/v1/deploy-keys", json={"name": "gone"})).json()["id"]
    r = await client.delete(f"/v1/deploy-keys/{kid}")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


async def test_delete_in_use_409_names_skills(
    client: AsyncClient, db_session: AsyncSession, tenant_id: str
) -> None:
    kid = (await client.post("/v1/deploy-keys", json={"name": "used"})).json()["id"]
    await _insert_skill_using_key(
        db_session, tenant_id=tenant_id, deploy_key_id=kid, name="uses-the-key"
    )
    r = await client.delete(f"/v1/deploy-keys/{kid}")
    assert r.status_code == 409, r.text
    body = r.json()
    assert "skill" in body["error"]["message"].lower()
    assert "uses-the-key" in body["error"]["message"]


async def test_create_git_skill_with_unknown_key_422(client: AsyncClient) -> None:
    r = await client.post("/v1/skills", json={
        "source_type": "git", "source_url": "git@github.com:org/repo.git",
        "source_ref": "main", "deploy_key_id": "dk_missing",
    })
    assert r.status_code == 422, r.text
    assert "deploy key" in r.json()["error"]["message"].lower()


async def test_create_git_skill_https_plus_key_422(client: AsyncClient) -> None:
    kid = (await client.post("/v1/deploy-keys", json={"name": "k1"})).json()["id"]
    r = await client.post("/v1/skills", json={
        "source_type": "git", "source_url": "https://github.com/org/repo",
        "source_ref": "main", "deploy_key_id": kid,
    })
    assert r.status_code == 422, r.text
    assert "ssh" in r.json()["error"]["message"].lower()


async def test_git_refs_with_key_passes_private_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    kid = (await client.post("/v1/deploy-keys", json={"name": "k2"})).json()["id"]
    seen: dict[str, Any] = {}

    def fake_list(url: str, *, private_key: str | None = None) -> tuple[list[str], str]:
        seen["pk"] = private_key
        return (["main"], "main")

    monkeypatch.setattr("control_plane.routers.skills.list_branches", fake_list)
    r = await client.post("/v1/skills/git-refs", json={
        "source_url": "git@github.com:org/repo.git", "deploy_key_id": kid,
    })
    assert r.status_code == 200, r.text
    assert seen["pk"] and "OPENSSH PRIVATE KEY" in seen["pk"]


async def test_create_with_misconfigured_master_key_is_500_not_400(
    db_session: AsyncSession, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server-side CREDENTIAL_ENCRYPTION_KEY misconfiguration must surface as
    a 500 (generic internal error), not a 400 blaming the ``name`` field.

    Uses its own client with ``raise_app_exceptions=False`` so the unhandled
    ValueError is turned into a response by the app's generic exception
    handler instead of propagating up through httpx.
    """

    def _broken_load_key() -> bytes:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not set")

    monkeypatch.setattr(
        "control_plane.routers.deploy_keys.load_key_from_env", _broken_load_key
    )
    app = _make_app(db_session, tenant_id)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        r = await c.post("/v1/deploy-keys", json={"name": "x"})
    assert r.status_code == 500, r.text
    assert "CREDENTIAL_ENCRYPTION_KEY" not in r.text


async def test_git_refs_with_non_string_deploy_key_id_400(client: AsyncClient) -> None:
    r = await client.post("/v1/skills/git-refs", json={
        "source_url": "git@github.com:org/repo.git", "deploy_key_id": {"x": 1},
    })
    assert r.status_code == 400, r.text
    assert r.json()["error"]["field"] == "deploy_key_id"
