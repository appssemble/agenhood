from __future__ import annotations

import logging

import pytest

import control_plane.docker_ctl.provision as p
from control_plane.config import Settings

pytestmark = pytest.mark.unit


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk",
        seed_llm_api_key="",
        agent_image_tag="dev",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
        agent_registry="",  # local mode: images.get succeeds on the fake
    )


class _FakeVolumes:
    def create(self, name):  # noqa: ANN001
        return object()

    def get(self, name):  # noqa: ANN001
        raise AssertionError("volume cleanup must not run on the happy path")


class _FakeContainer:
    ports: dict = {}

    def reload(self) -> None:
        pass


class _FakeContainers:
    def run(self, **kwargs):  # noqa: ANN003
        return _FakeContainer()


class _FakeImages:
    def get(self, ref):  # noqa: ANN001
        return object()


class _FakeClient:
    volumes = _FakeVolumes()
    containers = _FakeContainers()
    images = _FakeImages()


@pytest.mark.asyncio
async def test_provision_logs_phase_timings(monkeypatch, caplog):
    monkeypatch.setattr(p, "_docker_client", lambda: _FakeClient())

    async def fake_poll(base_url, token, timeout_s):  # noqa: ANN001
        return True

    monkeypatch.setattr(p, "_poll_readyz", fake_poll)

    with caplog.at_level(logging.INFO, logger="provision"):
        result = await p.provision_container(
            settings=_settings(),
            container_id="con_test",
            tenant_id="ten_test",
            image_tag="dev",
            max_workers=1,
            mem_limit="1g",
            cpus=1.0,
        )

    assert result.docker_name  # provision succeeded
    msgs = [r.getMessage() for r in caplog.records]
    assert any("con_test" in m and "image ready" in m for m in msgs)
    assert any("con_test" in m and "container started" in m for m in msgs)
    assert any("con_test" in m and "ready" in m and "total" in m for m in msgs)
