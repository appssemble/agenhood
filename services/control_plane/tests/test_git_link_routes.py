"""Route-level tests for the control-plane git link (pull mode) endpoints.

Exercises the real handlers end-to-end against a migrated Postgres
(``db_session`` fixture — skips when docker is unavailable). The shim's
``git_clone``/``git_verify`` are patched at the ``ShimClient`` class level so no
real agent is contacted; everything else (DB writes, key gen, encryption) runs
for real, and DB state is asserted by selecting from
``containers``/``linked_repos``/``git_remotes``.

Mirrors how ``test_git_router_unit.py`` patches shim calls with ``AsyncMock``
and how ``test_files_archive_router.py`` drives the router via an ASGI app with
``resolve_principal`` overridden.
"""
from __future__ import annotations

import base64
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# A valid base64 32-byte master key so load_key_from_env() works for keygen +
# secret encryption. Set before importing anything that reads it at call time.
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", base64.b64encode(b"A" * 32).decode())

from analytics_seed import insert_container, insert_tenant  # noqa: E402

from control_plane.app import create_app  # noqa: E402
from control_plane.auth.principal import Principal, resolve_principal  # noqa: E402
from control_plane.config import Settings  # noqa: E402
from control_plane.models_db import (  # noqa: E402
    containers,
    git_remotes,
    linked_repos,
    tasks,
)
from control_plane.shim_client import ShimClient  # noqa: E402

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

_CLONE_OK = {"sha": "a" * 40}


def _http_status_error(code: str) -> httpx.HTTPStatusError:
    """Build the error ShimClient.git_clone raises when the shim returns a real
    clone failure as HTTP 400 ``{"error":{"code","message"}}``."""
    request = httpx.Request("POST", "http://shim/git/clone")
    response = httpx.Response(
        400, json={"error": {"code": code, "message": f"{code} from shim"}},
        request=request,
    )
    return httpx.HTTPStatusError("clone failed", request=request, response=response)


class _Env:
    """Bundle the wired app, the assertion session, and the seeded container id."""

    def __init__(self, app: Any, session: AsyncSession, cid: str, tenant_id: str) -> None:
        self.app = app
        self.session = session
        self.cid = cid
        self.tenant_id = tenant_id

    def client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        )

    async def refresh(self) -> None:
        """Drop the assertion session's transaction so the next read sees rows
        the route's own session has since committed."""
        await self.session.rollback()

    async def git_mode(self) -> str:
        await self.refresh()
        return (
            await self.session.execute(
                sa.select(containers.c.git_mode).where(containers.c.id == self.cid)
            )
        ).scalar_one()

    async def linked_row(self) -> dict[str, Any] | None:
        await self.refresh()
        row = (
            await self.session.execute(
                sa.select(linked_repos).where(linked_repos.c.container_id == self.cid)
            )
        ).mappings().first()
        return dict(row) if row else None

    async def remote_enabled(self) -> bool | None:
        await self.refresh()
        return (
            await self.session.execute(
                sa.select(git_remotes.c.enabled).where(
                    git_remotes.c.container_id == self.cid
                )
            )
        ).scalar_one_or_none()


@pytest_asyncio.fixture
async def env(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    """Seed a fresh running container and wire an ASGI app at its DB.

    Unique ids per test so the session-scoped Postgres needs no cleanup.
    """
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"lk_ten_{suffix}"
    cid = f"lk_c_{suffix}"
    await insert_tenant(db_session, tenant_id)
    await insert_container(db_session, cid=cid, tenant_id=tenant_id, name="box")

    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    app = create_app(_SETTINGS)
    app.state.session_factory = factory
    app.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id=tenant_id, role="member", is_staff=False, user_id="usr_1"
    )
    try:
        yield _Env(app, db_session, cid, tenant_id)
    finally:
        app.dependency_overrides.clear()


async def _make_key(env: _Env, *, rotate: bool = False) -> dict[str, Any]:
    async with env.client() as c:
        r = await c.post(
            f"/v1/containers/{env.cid}/git/link/key",
            params={"rotate": "true"} if rotate else None,
        )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# key
# ---------------------------------------------------------------------------

async def test_link_key_generates_and_is_stable(env: _Env) -> None:
    first = await _make_key(env)
    assert first["public_key"].startswith("ssh-ed25519 ")
    assert first["key_type"] == "ed25519"

    # Same call without rotate returns the identical key.
    again = await _make_key(env)
    assert again["public_key"] == first["public_key"]
    assert again["fingerprint"] == first["fingerprint"]

    # ?rotate=true mints a new key.
    rotated = await _make_key(env, rotate=True)
    assert rotated["public_key"] != first["public_key"]


# ---------------------------------------------------------------------------
# link
# ---------------------------------------------------------------------------

async def test_link_clones_and_switches_mode(env: _Env) -> None:
    await _make_key(env)
    # Pre-existing enabled push remote must be disabled by linking (exclusivity).
    await env.session.execute(
        sa.insert(git_remotes).values(
            container_id=env.cid, url="git@github.com:a/push.git",
            branch="main", enabled=True,
        )
    )
    await env.session.commit()

    with patch.object(
        ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)
    ) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )

    assert r.status_code == 200, r.text
    clone.assert_awaited_once()
    view = r.json()["linked"]
    assert view["url"] == "git@github.com:a/b.git"
    assert view["branch"] == "main"
    assert view["last_clone_status"] == "cloned"
    # The private key/ciphertext is never in the response.
    assert "ssh_private_key" not in r.text and "ciphertext" not in r.text

    assert await env.git_mode() == "linked"
    assert await env.remote_enabled() is False
    row = await env.linked_row()
    assert row is not None and row["last_clone_status"] == "cloned"
    assert row["url"] == "git@github.com:a/b.git"


async def test_link_requires_confirm(env: _Env) -> None:
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock()) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main"},
            )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "confirm_required"
    clone.assert_not_awaited()
    assert await env.git_mode() == "snapshot"


async def test_link_requires_key_first(env: _Env) -> None:
    # No key generated yet -> 400 no_key (still mode snapshot).
    with patch.object(ShimClient, "git_clone", new=AsyncMock()) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "no_key"
    clone.assert_not_awaited()


async def test_link_409_when_task_running(env: _Env) -> None:
    await _make_key(env)
    await env.session.execute(
        sa.insert(tasks).values(
            id=f"tsk_{uuid.uuid4().hex[:8]}", tenant_id=env.tenant_id,
            container_id=env.cid, driver="vanilla", body={"prompt": "p"},
            config_snapshot={}, status="running",
        )
    )
    await env.session.commit()

    with patch.object(ShimClient, "git_clone", new=AsyncMock()) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "task_running"
    clone.assert_not_awaited()


async def test_link_clone_400_surfaces_real_code(env: _Env) -> None:
    """A shim clone failure (HTTP 400 auth_failed) must surface as a 400 with
    code ``auth_failed`` — NOT a blanket 502 shim_unreachable."""
    await _make_key(env)
    with patch.object(
        ShimClient, "git_clone",
        new=AsyncMock(side_effect=_http_status_error("auth_failed")),
    ):
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "auth_failed"
    # Mode stays snapshot; the failure is recorded on the row.
    assert await env.git_mode() == "snapshot"
    row = await env.linked_row()
    assert row is not None and row["last_clone_status"] == "failed"


async def test_link_clone_404_means_outdated_agent(env: _Env) -> None:
    """A 404 from the shim (no /git/clone route — old agent image) surfaces as a
    clear 'agent_outdated' message, not the generic 'could not reach the remote'."""
    await _make_key(env)
    request = httpx.Request("POST", "http://shim/git/clone")
    response = httpx.Response(404, json={"detail": "Not Found"}, request=request)
    not_found = httpx.HTTPStatusError("404", request=request, response=response)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(side_effect=not_found)):
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert r.status_code == 502, r.text
    assert r.json()["error"]["code"] == "agent_outdated"
    assert "older agent image" in r.json()["error"]["message"]
    assert await env.git_mode() == "snapshot"


async def test_link_clone_transport_error_is_502(env: _Env) -> None:
    """A genuine transport failure (shim down) maps to 502 shim_unreachable."""
    await _make_key(env)
    boom = httpx.ConnectError("connection refused")
    with patch.object(ShimClient, "git_clone", new=AsyncMock(side_effect=boom)):
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "shim_unreachable"
    assert await env.git_mode() == "snapshot"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

async def test_get_link_returns_null_when_unlinked(env: _Env) -> None:
    async with env.client() as c:
        r = await c.get(f"/v1/containers/{env.cid}/git/link")
    assert r.status_code == 200
    assert r.json() == {"linked": None}


async def test_get_link_returns_view_when_linked(env: _Env) -> None:
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)):
        async with env.client() as c:
            await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "dev",
                      "confirm": True},
            )
            r = await c.get(f"/v1/containers/{env.cid}/git/link")
    assert r.status_code == 200
    view = r.json()["linked"]
    assert view is not None
    assert view["url"] == "git@github.com:a/b.git"
    assert view["branch"] == "dev"
    assert "ssh_private_key" not in r.text


# ---------------------------------------------------------------------------
# unlink
# ---------------------------------------------------------------------------

async def test_unlink_sets_snapshot_mode_keeps_row(env: _Env) -> None:
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)):
        async with env.client() as c:
            await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert await env.git_mode() == "linked"

    async with env.client() as c:
        r = await c.delete(f"/v1/containers/{env.cid}/git/link")
    assert r.status_code == 204

    assert await env.git_mode() == "snapshot"
    # The row (and its pull key) survive for a future relink.
    row = await env.linked_row()
    assert row is not None
    assert row["ssh_public_key"] is not None
    assert row["url"] == "git@github.com:a/b.git"


# ---------------------------------------------------------------------------
# repull
# ---------------------------------------------------------------------------

async def test_repull_requires_confirm_and_calls_clone(env: _Env) -> None:
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)):
        async with env.client() as c:
            await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )

    # Without confirm -> 400, no clone.
    with patch.object(ShimClient, "git_clone", new=AsyncMock()) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link/repull", json={},
            )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "confirm_required"
    clone.assert_not_awaited()

    # With confirm -> clones again using the stored url/branch.
    with patch.object(
        ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)
    ) as clone:
        async with env.client() as c:
            r = await c.post(
                f"/v1/containers/{env.cid}/git/link/repull", json={"confirm": True},
            )
    assert r.status_code == 200, r.text
    clone.assert_awaited_once()
    _, kwargs = clone.call_args
    assert kwargs["url"] == "git@github.com:a/b.git"
    assert kwargs["branch"] == "main"
    assert r.json()["linked"]["last_clone_status"] == "cloned"


# ---------------------------------------------------------------------------
# snapshots gating (linked containers have no local snapshot history)
# ---------------------------------------------------------------------------

async def test_snapshots_disabled_when_linked(env: _Env) -> None:
    """A linked container's GET …/git/snapshots returns the disabled marker
    (with the linked repo coordinates) and never calls the shim."""
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)):
        async with env.client() as c:
            await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    assert await env.git_mode() == "linked"

    with patch.object(ShimClient, "git_log", new=AsyncMock()) as git_log:
        async with env.client() as c:
            r = await c.get(f"/v1/containers/{env.cid}/git/snapshots")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disabled"] is True
    assert body["snapshots"] == []
    assert body["linked"] == {"url": "git@github.com:a/b.git", "branch": "main"}
    # The shim git_log must NOT be consulted in linked mode.
    git_log.assert_not_awaited()


async def test_snapshots_not_disabled_in_snapshot_mode(env: _Env) -> None:
    """The default (snapshot) path is unchanged: it consults the shim git_log
    and carries no disabled marker."""
    with patch.object(
        ShimClient, "git_log", new=AsyncMock(return_value={"snapshots": []})
    ) as git_log:
        async with env.client() as c:
            r = await c.get(f"/v1/containers/{env.cid}/git/snapshots")

    assert r.status_code == 200, r.text
    body = r.json()
    assert "disabled" not in body
    assert body["snapshots"] == []
    git_log.assert_awaited_once()


# ---------------------------------------------------------------------------
# container view exposes git_mode
# ---------------------------------------------------------------------------

async def test_container_get_exposes_git_mode_default(env: _Env) -> None:
    async with env.client() as c:
        r = await c.get(f"/v1/containers/{env.cid}")
    assert r.status_code == 200, r.text
    assert r.json()["git_mode"] == "snapshot"


async def test_container_get_exposes_git_mode_linked(env: _Env) -> None:
    await _make_key(env)
    with patch.object(ShimClient, "git_clone", new=AsyncMock(return_value=_CLONE_OK)):
        async with env.client() as c:
            await c.post(
                f"/v1/containers/{env.cid}/git/link",
                json={"url": "git@github.com:a/b.git", "branch": "main",
                      "confirm": True},
            )
    async with env.client() as c:
        r = await c.get(f"/v1/containers/{env.cid}")
    assert r.status_code == 200, r.text
    assert r.json()["git_mode"] == "linked"
