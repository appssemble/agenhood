import asyncio
import os

import pytest

from agentcore.tools.base import ToolContext
from agentcore.tools.files import (
    DeleteFileTool,
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)

pytestmark = pytest.mark.unit


def ctx(ws):
    return ToolContext(workspace=str(ws), cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_write_then_read_round_trip(tmp_path):
    c = ctx(tmp_path)
    w = await WriteFileTool().run({"path": "a/b.txt", "content": "hello"}, c)
    assert w.ok
    assert os.path.exists(tmp_path / "a/b.txt")
    r = await ReadFileTool().run({"path": "a/b.txt"}, c)
    assert r.ok
    assert r.content == "hello"


@pytest.mark.asyncio
async def test_write_refuses_outside_workspace(tmp_path):
    c = ctx(tmp_path)
    res = await WriteFileTool().run({"path": "../evil.txt", "content": "x"}, c)
    assert not res.ok
    assert "outside" in res.content


@pytest.mark.asyncio
async def test_write_refuses_agent_runtime(tmp_path):
    c = ctx(tmp_path)
    res = await WriteFileTool().run(
        {"path": ".agent-runtime/x", "content": "x"}, c
    )
    assert not res.ok
    assert "reserved" in res.content


@pytest.mark.asyncio
async def test_read_missing_file_returns_error(tmp_path):
    c = ctx(tmp_path)
    res = await ReadFileTool().run({"path": "nope.txt"}, c)
    assert not res.ok
    assert "not found" in res.content.lower()


@pytest.mark.asyncio
async def test_edit_requires_unique_match(tmp_path):
    c = ctx(tmp_path)
    await WriteFileTool().run({"path": "f.txt", "content": "alpha beta alpha"}, c)
    # multiple matches → error, file unchanged
    multi = await EditFileTool().run(
        {"path": "f.txt", "old_string": "alpha", "new_string": "X"}, c
    )
    assert not multi.ok
    assert "2 times" in multi.content or "multiple" in multi.content.lower()
    assert (tmp_path / "f.txt").read_text() == "alpha beta alpha"


@pytest.mark.asyncio
async def test_edit_not_found(tmp_path):
    c = ctx(tmp_path)
    await WriteFileTool().run({"path": "f.txt", "content": "hello"}, c)
    res = await EditFileTool().run(
        {"path": "f.txt", "old_string": "absent", "new_string": "X"}, c
    )
    assert not res.ok
    assert "not found" in res.content.lower()


@pytest.mark.asyncio
async def test_edit_unique_match_succeeds(tmp_path):
    c = ctx(tmp_path)
    await WriteFileTool().run({"path": "f.txt", "content": "one two three"}, c)
    res = await EditFileTool().run(
        {"path": "f.txt", "old_string": "two", "new_string": "TWO"}, c
    )
    assert res.ok
    assert (tmp_path / "f.txt").read_text() == "one TWO three"


@pytest.mark.asyncio
async def test_list_files_returns_relative_paths(tmp_path):
    c = ctx(tmp_path)
    await WriteFileTool().run({"path": "x/a.txt", "content": "1"}, c)
    await WriteFileTool().run({"path": "b.txt", "content": "2"}, c)
    res = await ListFilesTool().run({}, c)
    assert res.ok
    assert "b.txt" in res.content
    assert "x/a.txt" in res.content


@pytest.mark.asyncio
async def test_list_files_excludes_agent_runtime(tmp_path):
    c = ctx(tmp_path)
    runtime = tmp_path / ".agent-runtime" / "events"
    runtime.mkdir(parents=True)
    (runtime / "t.jsonl").write_text("{}")
    await WriteFileTool().run({"path": "b.txt", "content": "2"}, c)
    res = await ListFilesTool().run({}, c)
    assert ".agent-runtime" not in res.content


@pytest.mark.asyncio
async def test_list_files_excludes_agent_state(tmp_path):
    c = ctx(tmp_path)
    state = tmp_path / ".agent-state" / "cache"
    state.mkdir(parents=True)
    (state / "secret.txt").write_text("secret")
    await WriteFileTool().run({"path": "b.txt", "content": "2"}, c)
    res = await ListFilesTool().run({}, c)
    assert ".agent-state" not in res.content


@pytest.mark.asyncio
async def test_delete_file_then_missing(tmp_path):
    c = ctx(tmp_path)
    await WriteFileTool().run({"path": "d.txt", "content": "x"}, c)
    res = await DeleteFileTool().run({"path": "d.txt"}, c)
    assert res.ok
    assert not os.path.exists(tmp_path / "d.txt")


@pytest.mark.asyncio
async def test_delete_refuses_directory(tmp_path):
    c = ctx(tmp_path)
    (tmp_path / "subdir").mkdir()
    res = await DeleteFileTool().run({"path": "subdir"}, c)
    assert not res.ok
    assert "directory" in res.content.lower()


def test_tools_self_register():
    import agentcore.tools.files  # noqa: F401 — import for side-effect registration
    from agentcore.tools.base import TOOLS
    for name in ("read_file", "write_file", "edit_file", "list_files", "delete_file"):
        assert name in TOOLS
