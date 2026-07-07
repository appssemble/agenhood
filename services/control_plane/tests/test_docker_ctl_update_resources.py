from __future__ import annotations

import asyncio

import pytest

from control_plane.docker_ctl import update_resources

pytestmark = pytest.mark.unit


class _FakeContainer:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def update(self, **kwargs):
        self._captured.update(kwargs)


class _FakeContainers:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def get(self, name: str) -> _FakeContainer:
        self._captured["docker_name"] = name
        return _FakeContainer(self._captured)


class _FakeClient:
    def __init__(self, captured: dict) -> None:
        self.containers = _FakeContainers(captured)


def test_update_resources_uses_cpu_period_and_quota_not_nano_cpus():
    # docker-py's Container.update() has no nano_cpus parameter (unlike
    # containers.run()) — CPU must go through cpu_period/cpu_quota, the same
    # 100ms-period math Docker itself uses internally for --cpus.
    captured: dict = {}
    client = _FakeClient(captured)
    asyncio.run(update_resources(client, "agent-x", "1g", 0.5))
    assert captured["docker_name"] == "agent-x"
    assert captured["mem_limit"] == "1g"
    assert captured["memswap_limit"] == "1g"
    assert captured["cpu_period"] == 100_000
    assert captured["cpu_quota"] == 50_000
    assert "nano_cpus" not in captured
