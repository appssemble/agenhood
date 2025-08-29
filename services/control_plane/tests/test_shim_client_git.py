from __future__ import annotations

import httpx
import pytest

from control_plane.shim_client import (
    ShimClient,
    ShimGitConflict,
    ShimGitNotFound,
)

pytestmark = pytest.mark.unit


def client_with(handler) -> ShimClient:
    c = ShimClient(base_url="http://shim", token="t")
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://shim"
    )
    return c


@pytest.mark.asyncio
async def test_git_log_and_status():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/git/log":
            return httpx.Response(200, json={"snapshots": []})
        return httpx.Response(200, json={"initialized": True})

    c = client_with(handler)
    assert await c.git_log() == {"snapshots": []}
    assert (await c.git_status())["initialized"] is True
    await c.aclose()


@pytest.mark.asyncio
async def test_git_rollback_maps_conflict_and_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "busy" in body:
            return httpx.Response(409, json={"detail": "a task is running"})
        if "missing" in body:
            return httpx.Response(404, json={"detail": "unknown sha"})
        return httpx.Response(200, json={"sha": "a" * 40})

    c = client_with(handler)
    with pytest.raises(ShimGitConflict):
        await c.git_rollback("busy")
    with pytest.raises(ShimGitNotFound):
        await c.git_rollback("missing")
    assert (await c.git_rollback("ok"))["sha"] == "a" * 40
    await c.aclose()


@pytest.mark.asyncio
async def test_git_push_and_verify_pass_through():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "sha": "b" * 40})

    c = client_with(handler)
    out = await c.git_push(url="https://x/y.git", ssh_private_key="tok", branch="main")
    assert out["ok"] is True
    out = await c.git_verify(url="https://x/y.git", ssh_private_key="tok")
    assert out["ok"] is True
    await c.aclose()


@pytest.mark.asyncio
async def test_git_verify_sends_ssh_key_and_returns_branches():
    import json as _json

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = _json.loads(request.read())
        return httpx.Response(
            200,
            json={"ok": True, "branches": ["main"], "default_branch": "main"},
        )

    c = client_with(handler)
    out = await c.git_verify(url="git@github.com:a/b.git", ssh_private_key="K")
    await c.aclose()
    assert out["branches"] == ["main"]
    assert captured["body"]["ssh_private_key"] == "K"
    assert "token" not in captured["body"]


@pytest.mark.asyncio
async def test_git_clone_posts_and_returns_sha():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/git/clone"
        return httpx.Response(200, json={"sha": "b" * 40})

    c = client_with(handler)
    res = await c.git_clone(url="git@h:o/r.git", ssh_private_key="k", branch="main")
    assert res == {"sha": "b" * 40}
    await c.aclose()
