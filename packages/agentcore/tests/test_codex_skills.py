# packages/agentcore/tests/test_codex_skills.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentcore.drivers.codex import CodexDriver, codex_home, skills_dir
from agentcore.models import AgentConfig, ResolvedLimits, ShimSkill, TaskBody

pytestmark = pytest.mark.unit


def test_skills_dir_is_agents_skills_under_codex_home(tmp_path):
    expected = Path(codex_home(str(tmp_path))) / ".agents" / "skills"
    assert skills_dir(str(tmp_path)) == str(expected)


async def test_run_materializes_skills_before_launch(tmp_path):
    # The codex binary is absent in unit tests, so run() hits the
    # codex_unavailable path — but materialization happens BEFORE the subprocess
    # launch, so the SKILL.md must already be on disk.
    events: list[tuple[str, dict]] = []

    async def emit(t, p):
        events.append((t, p))

    result = await CodexDriver().run(
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="codex", model="gpt-5-codex"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=5),
        credential="sk-stub",
        emit=emit,
        cancel=asyncio.Event(),
        workspace=str(tmp_path),
        skills=[ShimSkill(name="git-release", description="Make releases", body="# do")],
    )

    md = Path(skills_dir(str(tmp_path))) / "git-release" / "SKILL.md"
    assert md.exists()                       # written before the subprocess launch
    assert "name: git-release" in md.read_text()
    # a skills_materialized log event was emitted
    assert any(t == "log" and p.get("op") == "skills_materialized" for t, p in events)
    # The run can't succeed with a stub credential (codex_unavailable if the
    # binary is absent, else an auth/timeout failure) — either way the
    # materialization above already ran. Don't pin the exact reason so the test
    # is robust whether or not codex is installed on the host running the tests.
    assert result.success is False


async def test_run_uses_makedirs_agent_for_skills_dir(monkeypatch, tmp_path):
    """Regression: `.agents` is a brand-new intermediate the first time this
    runs. ensure_agent_dir only chowns the leaf it's given, leaving `.agents`
    root-owned and unwritable by the dropped agent user — makedirs_agent chowns
    every newly-created directory in the path, not just the leaf (same bug
    class that broke claude-code's session-resume transcript writes)."""
    calls: list[str] = []
    monkeypatch.setattr(
        "agentcore.sandbox.makedirs_agent", lambda p, *a, **k: calls.append(p)
    )

    async def emit(t, p):
        pass

    await CodexDriver().run(
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="codex", model="gpt-5-codex"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=5),
        credential="sk-stub",
        emit=emit,
        cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )
    assert calls == [skills_dir(str(tmp_path))]


async def test_run_empty_skills_writes_nothing(tmp_path):
    async def emit(t, p):
        pass

    await CodexDriver().run(
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="codex", model="gpt-5-codex"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=5),
        credential="sk-stub",
        emit=emit,
        cancel=asyncio.Event(),
        workspace=str(tmp_path),
        skills=[],
    )
    assert not (Path(skills_dir(str(tmp_path))) / "git-release").exists()
