from __future__ import annotations

import pytest

from agentcore.models import AgentConfig, ShimMcpServer, ShimTaskRequest, TaskBody, ResolvedLimits

pytestmark = pytest.mark.unit


def test_agent_config_mcp_servers_defaults_empty() -> None:
    cfg = AgentConfig(driver="opencode", model="m")
    assert cfg.mcp_servers == []


def test_shim_request_carries_mcp_servers() -> None:
    req = ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="opencode", model="m", mcp_servers=["mcp_a"]),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        llm_credential="k",
        mcp_servers=[ShimMcpServer(name="a", url="https://x", auth_type="bearer", secret="t")],
    )
    assert req.mcp_servers[0].auth_type == "bearer"
    assert req.config.mcp_servers == ["mcp_a"]


def test_shim_mcp_server_defaults() -> None:
    s = ShimMcpServer(name="a", url="https://x")
    assert s.auth_type == "none"
    assert s.auth_header_name == ""
    assert s.secret == ""
