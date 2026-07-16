import pytest

from agentcore.tools.base import ToolContext
from agentcore.tools.paths import PathError, safe_resolve

pytestmark = pytest.mark.unit


def _mk_skill(tmp_path, name="pdf-reports"):
    d = tmp_path / ".agent-runtime" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: pdf-reports\n---\nbody")
    (d / "helper.py").write_text("print('hi')")
    return d


def test_reserved_dir_still_rejected_by_default(tmp_path):
    _mk_skill(tmp_path)
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), ".agent-runtime/skills/pdf-reports/SKILL.md")


def test_skills_subtree_allowed_with_flag(tmp_path):
    d = _mk_skill(tmp_path)
    resolved = safe_resolve(
        str(tmp_path), ".agent-runtime/skills/pdf-reports/helper.py",
        allow_skills_read=True,
    )
    assert resolved == str(d / "helper.py")


def test_flag_does_not_open_rest_of_reserved_dir(tmp_path):
    (tmp_path / ".agent-runtime").mkdir()
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), ".agent-runtime/other.txt", allow_skills_read=True)
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), ".agent-state/x", allow_skills_read=True)


def test_flag_does_not_allow_workspace_escape(tmp_path):
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), "../outside", allow_skills_read=True)


@pytest.mark.asyncio
async def test_read_file_tool_reads_skill_file(tmp_path):
    import asyncio

    from agentcore.tools.files import ReadFileTool

    _mk_skill(tmp_path)
    ctx = ToolContext(workspace=str(tmp_path), cancel=asyncio.Event())
    res = await ReadFileTool().run(
        {"path": ".agent-runtime/skills/pdf-reports/helper.py"}, ctx
    )
    assert res.ok
    assert "print('hi')" in res.content


@pytest.mark.asyncio
async def test_write_file_tool_still_rejects_skills_subtree(tmp_path):
    import asyncio

    from agentcore.tools.files import WriteFileTool

    _mk_skill(tmp_path)
    ctx = ToolContext(workspace=str(tmp_path), cancel=asyncio.Event())
    res = await WriteFileTool().run(
        {"path": ".agent-runtime/skills/pdf-reports/SKILL.md", "content": "x"}, ctx
    )
    assert not res.ok
