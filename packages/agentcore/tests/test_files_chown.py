from __future__ import annotations

import asyncio

import pytest

from agentcore.tools import files
from agentcore.tools.base import ToolContext

pytestmark = pytest.mark.unit


def _ctx(ws):
    return ToolContext(workspace=str(ws), cancel=asyncio.Event())


def test_write_file_chowns_when_root(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(files.sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(files.sandbox.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    res = asyncio.run(
        files.WriteFileTool().run({"path": "a.txt", "content": "hi"}, _ctx(tmp_path))
    )
    assert res.ok
    assert calls and calls[0][1] == files.sandbox.AGENT_UID


def test_write_file_no_chown_when_not_root(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(files.sandbox.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(files.sandbox.os, "chown", lambda p, u, g: calls.append(p))
    res = asyncio.run(
        files.WriteFileTool().run({"path": "a.txt", "content": "hi"}, _ctx(tmp_path))
    )
    assert res.ok
    assert calls == []
