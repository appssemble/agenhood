import pytest

pytestmark = pytest.mark.unit


def test_build_task_skills_resolves_for_claude_code(monkeypatch):
    from control_plane.routers import tasks as tasks_mod
    from agentcore.models import AgentConfig, ShimSkill

    monkeypatch.setattr(
        tasks_mod,
        "resolve_skills_for_request",
        lambda ids, rows: [ShimSkill(name="demo", description="d", body="x")],
    )
    cfg = AgentConfig(driver="claude-code", model="claude-opus-4-8", skills=["s1"])
    out = tasks_mod.build_task_skills(cfg, [{"id": "s1"}])
    assert [s.name for s in out] == ["demo"]


def test_build_task_skills_empty_when_no_skills(monkeypatch):
    from control_plane.routers import tasks as tasks_mod
    from agentcore.models import AgentConfig

    cfg = AgentConfig(driver="claude-code", model="claude-opus-4-8", skills=[])
    assert tasks_mod.build_task_skills(cfg, []) == []


def test_build_task_mcp_resolves_for_claude_code(monkeypatch):
    from control_plane.routers import tasks as tasks_mod
    from agentcore.models import AgentConfig, ShimMcpServer

    monkeypatch.setattr(
        tasks_mod,
        "resolve_mcp_for_request",
        lambda ids, rows, key: [ShimMcpServer(name="gh", url="https://x")],
    )
    cfg = AgentConfig(driver="claude-code", model="claude-opus-4-8", mcp_servers=["m1"])
    out = tasks_mod.build_task_mcp_servers(cfg, [{"id": "m1"}], b"key")
    assert [s.name for s in out] == ["gh"]
