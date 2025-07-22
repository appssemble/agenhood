# packages/agentcore/tests/test_opencode_skills.py
from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.drivers.opencode import materialize_skills, skills_dir, workspace_xdg
from agentcore.models import ShimSkill

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
async def test_materialize_skips_invalid_names(tmp_path):
    # An invalid name must never escape the skills dir or crash. The only skill
    # is invalid, so NO SKILL.md may be written anywhere under the workspace —
    # this catches a traversal at its real target dir, not just <tmp>/escape.
    skills = [ShimSkill(name="../escape", description="d", body="")]
    written = await materialize_skills(str(tmp_path), skills)
    assert written == []
    assert list(Path(tmp_path).rglob("SKILL.md")) == []
