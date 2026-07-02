from __future__ import annotations

import httpx
import pytest

import control_plane.registry as registry
from control_plane.config import Settings

pytestmark = pytest.mark.unit


def _settings(**kw) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seed",
        seed_llm_api_key="",
        agent_image_tag="dev",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
    )
    base.update(kw)
    return Settings(**base)


class _Img:
    def __init__(self, tags: list[str]) -> None:
        self.tags = tags


class _Images:
    def __init__(self, imgs: list[_Img]) -> None:
        self._imgs = imgs

    def list(self, name=None):
        return self._imgs


class _Client:
    def __init__(self, imgs: list[_Img]) -> None:
        self.images = _Images(imgs)


@pytest.mark.asyncio
async def test_merges_registry_and_local_registry_wins(monkeypatch) -> None:
    async def fake_reg(settings):
        return ["v2", "v1"]

    monkeypatch.setattr(registry, "_registry_tags", fake_reg)
    client = _Client([_Img(["agent-runtime:dev"]), _Img(["reg.example/agent-runtime:v1"])])
    out = await registry.list_image_tags(_settings(agent_registry="reg.example"), client)
    by_tag = {t["tag"]: t["source"] for t in out["tags"]}
    assert by_tag == {"v1": "registry", "v2": "registry", "dev": "local"}
    assert out["registry_unavailable"] is False
    assert out["default_tag"] == "dev"


@pytest.mark.asyncio
async def test_registry_error_falls_back_to_local(monkeypatch) -> None:
    async def boom(settings):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(registry, "_registry_tags", boom)
    client = _Client([_Img(["agent-runtime:dev"])])
    out = await registry.list_image_tags(_settings(agent_registry="reg.example"), client)
    assert out["registry_unavailable"] is True
    assert {t["tag"] for t in out["tags"]} == {"dev"}


@pytest.mark.asyncio
async def test_local_only_no_registry_call(monkeypatch) -> None:
    async def fail(settings):  # must NOT be called when registry is empty
        raise AssertionError("registry queried in local-only mode")

    monkeypatch.setattr(registry, "_registry_tags", fail)
    client = _Client([_Img(["agent-runtime:dev"]), _Img(["agent-runtime:custom"])])
    out = await registry.list_image_tags(_settings(agent_registry=""), client)
    assert out["registry_unavailable"] is False
    assert {t["tag"] for t in out["tags"]} == {"dev", "custom"}
    assert all(t["source"] == "local" for t in out["tags"])


def test_tags_list_url_bare_host() -> None:
    # Self-hosted registry: the whole value is the host, repo directly under /v2/.
    assert (
        registry._tags_list_url("registry.example.com")
        == "https://registry.example.com/v2/agent-runtime/tags/list"
    )


def test_tags_list_url_host_with_namespace() -> None:
    # GHCR: only "ghcr.io" is the host; "appssemble" is the repo namespace and
    # must land AFTER /v2/, not before it.
    assert (
        registry._tags_list_url("ghcr.io/appssemble")
        == "https://ghcr.io/v2/appssemble/agent-runtime/tags/list"
    )


def test_parse_bearer_challenge() -> None:
    header = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:appssemble/agent-runtime:pull"'
    assert registry._parse_bearer_challenge(header) == {
        "realm": "https://ghcr.io/token",
        "service": "ghcr.io",
        "scope": "repository:appssemble/agent-runtime:pull",
    }
    # Non-Bearer challenges (e.g. Basic) yield no params.
    assert registry._parse_bearer_challenge('Basic realm="x"') == {}


@pytest.mark.asyncio
async def test_registry_tags_honors_ghcr_bearer_challenge(monkeypatch) -> None:
    """A GHCR-style 401 Bearer challenge is exchanged for an anonymous token and
    the tags/list call is retried with it."""
    calls: list[tuple[str, dict, tuple | None]] = []

    class _Resp:
        def __init__(self, status: int, *, headers=None, json_body=None) -> None:
            self.status_code = status
            self.headers = headers or {}
            self._json = json_body or {}

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)

    class _FakeClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *, params=None, auth=None, headers=None):
            calls.append((url, params or {}, auth))
            if url.endswith("/tags/list") and not (headers or {}).get("Authorization"):
                return _Resp(
                    401,
                    headers={
                        "www-authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:appssemble/agent-runtime:pull"'
                    },
                )
            if url == "https://ghcr.io/token":
                return _Resp(200, json_body={"token": "anon-tok"})
            # Retried tags/list with the bearer token.
            return _Resp(200, json_body={"tags": ["1.0.0", "1.0.0-full"]})

    monkeypatch.setattr(registry.httpx, "AsyncClient", _FakeClient)
    tags = await registry._registry_tags(_settings(agent_registry="ghcr.io/appssemble"))
    assert tags == ["1.0.0", "1.0.0-full"]

    # Anonymous public flow: no basic auth was sent to the token endpoint, and
    # the challenge's service/scope were forwarded.
    token_call = next(c for c in calls if c[0] == "https://ghcr.io/token")
    assert token_call[2] is None
    assert token_call[1] == {
        "service": "ghcr.io",
        "scope": "repository:appssemble/agent-runtime:pull",
    }
