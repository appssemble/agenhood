from __future__ import annotations

import asyncio

import pytest

from control_plane.config import Settings
from control_plane.docker_ctl import run_from_volume

pytestmark = pytest.mark.unit


class _FakeContainer:
    def __init__(self) -> None:
        self.ports: dict = {}

    def reload(self) -> None:
        pass


class _FakeContainers:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def run(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeContainer()


class _FakeClient:
    def __init__(self, captured: dict) -> None:
        self.containers = _FakeContainers(captured)


def _settings(**over):
    base = dict(
        database_url="x", seed_tenant_id="t", seed_api_key="k", seed_llm_api_key="",
        agent_image_tag="dev", internal_network="agent-runtime-internal",
        readyz_timeout_seconds=1.0, shim_port=8080,
    )
    base.update(over)
    return Settings(**base)


def test_run_from_volume_uses_row_resources_not_settings_defaults():
    captured: dict = {}
    client = _FakeClient(captured)
    row = {
        "id": "con_1", "docker_name": "agent-x", "volume_name": "vol-x",
        "image_tag": "dev", "shim_token": "tok", "tenant_id": "t1",
        "mem_limit": "3g", "cpus": 1.5,
    }
    asyncio.run(run_from_volume(client, row, settings=_settings()))
    assert captured["mem_limit"] == "3g"
    assert captured["memswap_limit"] == "3g"
    assert captured["cpu_period"] == 100_000
    assert captured["cpu_quota"] == 150_000
