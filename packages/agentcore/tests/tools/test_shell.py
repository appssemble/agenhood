# packages/agentcore/tests/tools/test_shell.py
import asyncio

import pytest

from agentcore.tools.base import ToolContext
from agentcore.tools.shell import BashTool, PythonTool

pytestmark = pytest.mark.unit


def ctx(ws):
    return ToolContext(workspace=str(ws), cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_bash_captures_stdout_stderr_exit(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run(
        {"command": "echo out; echo err 1>&2; exit 3"}, c
    )
    assert not res.ok  # non-zero exit
    assert "out" in res.content
    assert "err" in res.content
    assert "exit code: 3" in res.content


@pytest.mark.asyncio
async def test_bash_runs_in_workspace_cwd(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run({"command": "pwd"}, c)
    assert res.ok
    import os
    assert os.path.realpath(str(tmp_path)) in res.content


@pytest.mark.asyncio
async def test_bash_timeout_kills_process(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run({"command": "sleep 5", "timeout": 1}, c)
    assert not res.ok
    assert "timed out" in res.content.lower()
    assert res.duration_ms < 4000


@pytest.mark.asyncio
async def test_bash_timeout_capped_at_600(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run({"command": "echo hi", "timeout": 99999}, c)
    assert res.ok  # capping does not break a fast command


@pytest.mark.asyncio
async def test_python_runs_snippet(tmp_path):
    c = ctx(tmp_path)
    res = await PythonTool().run({"code": "print(2 + 2)"}, c)
    assert res.ok
    assert "4" in res.content


@pytest.mark.asyncio
async def test_python_reports_traceback(tmp_path):
    c = ctx(tmp_path)
    res = await PythonTool().run({"code": "raise ValueError('boom')"}, c)
    assert not res.ok
    assert "ValueError" in res.content
    assert "boom" in res.content


@pytest.mark.asyncio
async def test_bash_missing_command_is_error_result(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run({}, c)
    assert not res.ok  # must not raise KeyError


@pytest.mark.asyncio
async def test_bash_bad_timeout_type_is_error_result(tmp_path):
    c = ctx(tmp_path)
    res = await BashTool().run({"command": "echo hi", "timeout": "soon"}, c)
    assert not res.ok  # must not raise ValueError


@pytest.mark.asyncio
async def test_python_missing_code_is_error_result(tmp_path):
    c = ctx(tmp_path)
    res = await PythonTool().run({}, c)
    assert not res.ok  # must not raise KeyError


@pytest.mark.asyncio
async def test_python_bad_timeout_type_is_error_result(tmp_path):
    c = ctx(tmp_path)
    res = await PythonTool().run({"code": "print(1)", "timeout": "soon"}, c)
    assert not res.ok  # must not raise ValueError


def test_shell_tools_self_register():
    import agentcore.tools.shell  # noqa: F401
    from agentcore.tools.base import TOOLS
    assert "bash" in TOOLS
    assert "python" in TOOLS
