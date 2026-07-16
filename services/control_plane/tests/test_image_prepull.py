from __future__ import annotations

import pytest

import control_plane.image_prepull as prepull
from control_plane.config import Settings
from control_plane.docker_ctl.provision import ImageUnavailable

pytestmark = pytest.mark.unit


def _settings(**kw) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk",
        seed_llm_api_key="",
        agent_image_tag="1.3.1",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
        agent_registry="reg.example",
    )
    base.update(kw)
    return Settings(**base)


@pytest.mark.asyncio
async def test_ensure_calls_pull_or_verify_with_default_tag(monkeypatch):
    calls: list[tuple] = []

    def fake_pull(client, settings, tag, *, force=False):
        calls.append((tag, force))
        return f"reg.example/agent-runtime:{tag}"

    monkeypatch.setattr(prepull.provision, "pull_or_verify_image", fake_pull)
    await prepull.ensure_agent_image(object(), _settings())
    assert calls == [("1.3.1", False)]


@pytest.mark.asyncio
async def test_ensure_swallows_image_unavailable(monkeypatch, caplog):
    def fake_pull(client, settings, tag, *, force=False):
        raise ImageUnavailable("registry down")

    monkeypatch.setattr(prepull.provision, "pull_or_verify_image", fake_pull)
    with caplog.at_level("WARNING", logger="image_prepull"):
        await prepull.ensure_agent_image(object(), _settings())  # must not raise
    assert any("pre-pull failed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_ensure_swallows_unexpected_errors(monkeypatch, caplog):
    def fake_pull(client, settings, tag, *, force=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(prepull.provision, "pull_or_verify_image", fake_pull)
    with caplog.at_level("ERROR", logger="image_prepull"):
        await prepull.ensure_agent_image(object(), _settings())  # must not raise
    assert any("pre-pull failed" in r.getMessage() for r in caplog.records)
