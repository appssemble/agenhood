import asyncio

import pytest

from agentcore.drivers.skill_tool import SkillTool, skills_dir
from agentcore.tools.base import ToolContext

pytestmark = pytest.mark.unit


def _ctx(tmp_path):
    return ToolContext(workspace=str(tmp_path), cancel=asyncio.Event())


def _materialize(tmp_path, name="pdf-reports", body="Render with helper.py"):
    d = tmp_path / ".agent-runtime" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}")
    return d


def test_skills_dir_layout(tmp_path):
    assert skills_dir(str(tmp_path)) == str(tmp_path / ".agent-runtime" / "skills")


@pytest.mark.asyncio
async def test_skill_tool_returns_content_with_base_dir_prefix(tmp_path):
    _materialize(tmp_path)
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["pdf-reports"])
    res = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert res.ok
    assert res.content.startswith(
        f"Base directory for this skill: {skills_dir(str(tmp_path))}/pdf-reports"
    )
    assert "Render with helper.py" in res.content


@pytest.mark.asyncio
async def test_skill_tool_unknown_name_lists_valid_names(tmp_path):
    _materialize(tmp_path)
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["pdf-reports"])
    res = await tool.run({"name": "nope"}, _ctx(tmp_path))
    assert not res.ok
    assert "nope" in res.content and "pdf-reports" in res.content


@pytest.mark.asyncio
async def test_skill_tool_name_not_in_written_list_rejected(tmp_path):
    # On disk but not in the accepted-names list (e.g. bundle failed) -> error.
    _materialize(tmp_path, name="ghost")
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=[])
    res = await tool.run({"name": "ghost"}, _ctx(tmp_path))
    assert not res.ok


@pytest.mark.asyncio
async def test_skill_tool_missing_file_is_error_result(tmp_path):
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["pdf-reports"])
    res = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert not res.ok  # accepted name but file vanished -> error result, no raise
