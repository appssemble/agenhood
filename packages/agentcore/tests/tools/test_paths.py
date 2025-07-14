import os

import pytest

from agentcore.tools.paths import PathError, safe_resolve

pytestmark = pytest.mark.unit


def test_resolves_relative_inside_workspace(tmp_path):
    ws = str(tmp_path)
    resolved = safe_resolve(ws, "notes/report.md")
    assert resolved == os.path.join(ws, "notes/report.md")


def test_resolves_absolute_workspace_path(tmp_path):
    ws = str(tmp_path)
    resolved = safe_resolve(ws, f"{ws}/a.txt")
    assert resolved == os.path.join(ws, "a.txt")


def test_rejects_parent_traversal(tmp_path):
    ws = str(tmp_path)
    with pytest.raises(PathError, match="outside"):
        safe_resolve(ws, "../escape.txt")


def test_rejects_absolute_outside_workspace(tmp_path):
    ws = str(tmp_path)
    with pytest.raises(PathError, match="outside"):
        safe_resolve(ws, "/etc/passwd")


def test_rejects_agent_runtime_dir(tmp_path):
    ws = str(tmp_path)
    with pytest.raises(PathError, match="reserved"):
        safe_resolve(ws, ".agent-runtime/events/x.jsonl")


def test_rejects_symlink_escape(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (ws / "link").symlink_to(outside)
    with pytest.raises(PathError, match="outside"):
        safe_resolve(str(ws), "link")


def test_safe_resolve_rejects_agent_runtime(tmp_path):
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), ".agent-runtime/events/x.jsonl")


def test_safe_resolve_rejects_agent_state(tmp_path):
    with pytest.raises(PathError):
        safe_resolve(str(tmp_path), ".agent-state/codex/auth.json")


def test_safe_resolve_allows_normal_path(tmp_path):
    out = safe_resolve(str(tmp_path), "src/main.py")
    assert out.endswith("/src/main.py")
