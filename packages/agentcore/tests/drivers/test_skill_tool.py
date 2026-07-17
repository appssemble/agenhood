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


@pytest.mark.asyncio
async def test_frontmatter_stripped_from_result(tmp_path):
    _materialize(tmp_path, body="Do the thing.")
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["pdf-reports"])
    res = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert res.ok
    assert "---" not in res.content
    assert "name: pdf-reports" not in res.content
    assert "Do the thing." in res.content
    assert res.content.startswith("Base directory for this skill:")


@pytest.mark.asyncio
async def test_no_frontmatter_passthrough(tmp_path):
    d = tmp_path / ".agent-runtime" / "skills" / "plain"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("Just instructions, no frontmatter.")
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["plain"])
    res = await tool.run({"name": "plain"}, _ctx(tmp_path))
    assert res.ok
    assert "Just instructions, no frontmatter." in res.content


@pytest.mark.asyncio
async def test_unterminated_frontmatter_returns_raw(tmp_path):
    d = tmp_path / ".agent-runtime" / "skills" / "broken"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: broken\nno terminator here")
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["broken"])
    res = await tool.run({"name": "broken"}, _ctx(tmp_path))
    assert res.ok
    assert "no terminator here" in res.content  # raw fallback, never raises


@pytest.mark.asyncio
async def test_claude_skill_dir_substituted(tmp_path):
    _materialize(tmp_path, body="Run ${CLAUDE_SKILL_DIR}/helper.py now.")
    base = skills_dir(str(tmp_path))
    tool = SkillTool(base_dir=base, names=["pdf-reports"])
    res = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert "${CLAUDE_SKILL_DIR}" not in res.content
    assert f"Run {base}/pdf-reports/helper.py now." in res.content


@pytest.mark.asyncio
async def test_second_call_returns_already_loaded_note(tmp_path):
    _materialize(tmp_path, body="Body once.")
    tool = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["pdf-reports"])
    first = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    second = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert first.ok and "Body once." in first.content
    assert second.ok
    assert second.content == "Skill 'pdf-reports' is already loaded in this conversation."
    # A failed load must NOT mark the skill as served:
    tool2 = SkillTool(base_dir=skills_dir(str(tmp_path)), names=["ghost"])
    missing = await tool2.run({"name": "ghost"}, _ctx(tmp_path))
    assert not missing.ok  # file absent
    # (no dedup assertion for the failure — it simply must not record)


@pytest.mark.asyncio
async def test_skill_cap_truncates_with_path_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_CONTENT_MAX_CHARS", "100")
    _materialize(tmp_path, body="x" * 5000)
    base = skills_dir(str(tmp_path))
    tool = SkillTool(base_dir=base, names=["pdf-reports"])
    res = await tool.run({"name": "pdf-reports"}, _ctx(tmp_path))
    assert res.ok
    assert len(res.content) < 600  # accounts for path length variations in test environment
    assert "truncated" in res.content
    assert f"{base}/pdf-reports/SKILL.md" in res.content


def test_strip_frontmatter_bare_delimiters():
    """Test that frontmatter is only stripped when delimited by bare --- lines."""
    from agentcore.drivers.skill_tool import _strip_frontmatter

    # Standard case: body with proper frontmatter
    result = _strip_frontmatter("---\nname: x\n---\nBody")
    assert result == "Body"

    # Body starting with horizontal rule (not proper frontmatter) -> return raw
    result = _strip_frontmatter("--- Horizontal rule intro\ntext\n----\nmore")
    assert result == "--- Horizontal rule intro\ntext\n----\nmore"

    # Frontmatter with non-bare closer in body: scanner skips non-bare --- and finds real closer
    result = _strip_frontmatter("---\nname: x\n--- xx\nreal\n---\nBody")
    assert result == "Body"

    # No frontmatter at all
    result = _strip_frontmatter("Just body content")
    assert result == "Just body content"

    # Frontmatter with no closer -> return raw
    result = _strip_frontmatter("---\nname: x\nno closer")
    assert result == "---\nname: x\nno closer"

    # Frontmatter at end of string (no body after)
    result = _strip_frontmatter("---\nname: x\n---")
    assert result == ""

    # Frontmatter followed by empty lines and body
    result = _strip_frontmatter("---\nname: x\n---\n\n\nBody")
    assert result == "Body"


@pytest.mark.asyncio
async def test_failed_load_does_not_mark_skill_served(tmp_path):
    """Failed load should not mark skill as served; subsequent file creation
    should return full content, not the 'already loaded' message."""
    base = skills_dir(str(tmp_path))
    tool = SkillTool(base_dir=base, names=["late"])

    # First call: skill name is accepted but file doesn't exist yet -> fails
    res1 = await tool.run({"name": "late"}, _ctx(tmp_path))
    assert not res1.ok
    assert "could not load skill" in res1.content

    # Now create the skill file
    d = tmp_path / ".agent-runtime" / "skills" / "late"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("Late body.")

    # Second call: file now exists -> should return full content, NOT "already loaded"
    res2 = await tool.run({"name": "late"}, _ctx(tmp_path))
    assert res2.ok
    assert "Late body." in res2.content
    assert "already loaded" not in res2.content
    assert res2.content.startswith(f"Base directory for this skill: {base}/late")
