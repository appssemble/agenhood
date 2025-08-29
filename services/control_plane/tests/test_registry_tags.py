from __future__ import annotations

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
