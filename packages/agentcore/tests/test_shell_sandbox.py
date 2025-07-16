from __future__ import annotations

import asyncio

import pytest

from agentcore.tools import shell
from agentcore.tools.base import ToolContext

pytestmark = pytest.mark.unit


def _ctx(ws):
    return ToolContext(workspace=str(ws), cancel=asyncio.Event())


def test_bash_does_not_leak_shim_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIM_TOKEN", "secret")
    res = asyncio.run(
        shell.BashTool().run({"command": "echo TOK=${SHIM_TOKEN:-absent}"}, _ctx(tmp_path))
    )
    assert "TOK=absent" in res.content
    assert "secret" not in res.content


def test_bash_keeps_path(tmp_path):
    res = asyncio.run(shell.BashTool().run({"command": "echo $PATH"}, _ctx(tmp_path)))
    assert res.ok
    assert res.content.strip() != ""
