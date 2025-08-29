"""Regression: run_from_volume must wire the egress proxy env, like provision.

Containers are attached to the internal-only ``agent-runtime-internal`` network,
so their ONLY outbound path is the egress proxy via HTTP_PROXY/HTTPS_PROXY. When
rehydrate/recover re-created a container without those vars, the agent's LLM
calls had no route out and every task hung at "running" (never progressed).
"""
from __future__ import annotations

from typing import Any

import pytest

from control_plane import docker_ctl

pytestmark = pytest.mark.unit


class _FakeNewContainer:
    ports: dict[str, Any] = {}

    def reload(self) -> None:  # pragma: no cover - not used without bind_to_host
        pass


class _CapturingContainers:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def run(self, **kwargs: Any) -> _FakeNewContainer:
        self.kwargs = kwargs
        return _FakeNewContainer()


class _CapturingClient:
    def __init__(self) -> None:
        self.containers = _CapturingContainers()


@pytest.mark.asyncio
async def test_run_from_volume_includes_egress_proxy_and_search_env() -> None:
    client = _CapturingClient()
    row = {
        "id": "con_1",
        "docker_name": "agent-c-1",
        "volume_name": "vol_1",
        "image_tag": "v0.2.0",
        "shim_token": "tok-123",
        "tenant_id": "ten_1",
    }

    await docker_ctl.run_from_volume(client, row, network="agent-runtime-internal")

    env = client.containers.kwargs["environment"]
    # The egress proxy wiring that was missing (the bug):
    assert env["HTTP_PROXY"] == "http://egress-proxy:8888"
    assert env["HTTPS_PROXY"] == "http://egress-proxy:8888"
    assert "searxng" in env["NO_PROXY"]
    assert env["SEARCH_PROVIDER_URL"] == "http://searxng:8080"
    # Identity env still present:
    assert env["SHIM_TOKEN"] == "tok-123"
    assert env["CONTAINER_ID"] == "con_1"
    assert env["TENANT_ID"] == "ten_1"


@pytest.mark.asyncio
async def test_run_from_volume_extra_env_overrides() -> None:
    client = _CapturingClient()
    row = {
        "id": "con_2",
        "docker_name": "agent-c-2",
        "volume_name": "vol_2",
        "image_tag": "v0.2.0",
        "shim_token": "tok",
        "tenant_id": "ten_2",
    }

    await docker_ctl.run_from_volume(
        client, row, network="agent-runtime-internal", extra_env={"HTTPS_PROXY": "http://stub:9"}
    )

    env = client.containers.kwargs["environment"]
    assert env["HTTPS_PROXY"] == "http://stub:9"  # extra_env wins (integration stub LLM)


@pytest.mark.asyncio
async def test_run_from_volume_uses_registry_prefixed_image() -> None:
    """Recovered/rehydrated agents must resolve the SAME registry-prefixed image
    ref as fresh provisioning (build_run_kwargs sources the prefix from settings),
    and the per-container row image_tag must win over settings.agent_image_tag."""
    from control_plane.config import Settings

    client = _CapturingClient()
    row = {
        "id": "con_3",
        "docker_name": "agent-c-3",
        "volume_name": "vol_3",
        "image_tag": "v0.2.0",  # per-container tag (differs from settings default below)
        "shim_token": "tok",
        "tenant_id": "ten_3",
    }
    settings = Settings(
        database_url="x",
        seed_tenant_id="t",
        seed_api_key="k",
        seed_llm_api_key="",
        agent_image_tag="v0.3.0",  # global default — must NOT win over the row tag
        internal_network="agent-runtime-internal",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
        agent_registry="registry.example.com",
    )

    await docker_ctl.run_from_volume(
        client, row, settings=settings, network="agent-runtime-internal"
    )

    assert client.containers.kwargs["image"] == "registry.example.com/agent-runtime:v0.2.0"
