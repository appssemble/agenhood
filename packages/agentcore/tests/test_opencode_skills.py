# packages/agentcore/tests/test_opencode_skills.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentcore.drivers.opencode import (
    OpencodeDriver,
    materialize_skills,
    skills_dir,
    workspace_xdg,
)
from agentcore.models import AgentConfig, ResolvedLimits, ShimSkill, TaskBody

pytestmark = pytest.mark.unit


def test_skills_dir_is_under_xdg_config(tmp_path):
    expected = Path(workspace_xdg(str(tmp_path))["XDG_CONFIG_HOME"]) / "opencode" / "skills"
    assert skills_dir(str(tmp_path)) == str(expected)


@pytest.mark.asyncio
async def test_materialize_writes_skill_md_per_skill(tmp_path):
    skills = [
        ShimSkill(name="git-release", description="Make releases", body="# Steps\n1"),
        ShimSkill(name="lint", description="Run linters", body=""),
    ]
    written = await materialize_skills(str(tmp_path), skills)
    base = Path(skills_dir(str(tmp_path)))
    md = (base / "git-release" / "SKILL.md").read_text()
    assert "name: git-release" in md
    assert 'description: "Make releases"' in md
    assert "# Steps" in md
    assert (base / "lint" / "SKILL.md").exists()
    assert sorted(written) == ["git-release", "lint"]


@pytest.mark.asyncio
async def test_materialize_clears_stale_skills(tmp_path):
    base = Path(skills_dir(str(tmp_path)))
    (base / "old").mkdir(parents=True)
    (base / "old" / "SKILL.md").write_text("stale")
    await materialize_skills(str(tmp_path), [ShimSkill(name="new", description="d", body="")])
    assert not (base / "old").exists()              # stale skill removed
    assert (base / "new" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_materialize_empty_list_is_noop(tmp_path):
    written = await materialize_skills(str(tmp_path), [])
    assert written == []


@pytest.mark.asyncio
async def test_run_uses_makedirs_agent_for_skills_dir(monkeypatch, tmp_path):
    """Regression: `config/opencode` is a brand-new intermediate the first time
    this runs. ensure_agent_dir only chowns the leaf it's given, leaving
    `config/opencode` root-owned and unwritable by the dropped agent user —
    makedirs_agent chowns every newly-created directory in the path, not just
    the leaf (same bug class that broke claude-code's session-resume
    transcript writes)."""
    calls: list[str] = []
    monkeypatch.setattr(
        "agentcore.sandbox.makedirs_agent", lambda p, *a, **k: calls.append(p)
    )
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)

    async def emit(t, p):
        pass

    await OpencodeDriver().run(
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="opencode", model="claude-opus-4-8"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=5),
        credential="sk-stub",
        emit=emit,
        cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )
    assert calls == [skills_dir(str(tmp_path))]


@pytest.mark.asyncio
async def test_materialize_skips_invalid_names(tmp_path):
    # An invalid name must never escape the skills dir or crash. The only skill
    # is invalid, so NO SKILL.md may be written anywhere under the workspace —
    # this catches a traversal at its real target dir, not just <tmp>/escape.
    skills = [ShimSkill(name="../escape", description="d", body="")]
    written = await materialize_skills(str(tmp_path), skills)
    assert written == []
    assert list(Path(tmp_path).rglob("SKILL.md")) == []
