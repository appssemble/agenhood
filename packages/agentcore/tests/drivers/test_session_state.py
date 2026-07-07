from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def test_session_state_path_layout():
    from agentcore.drivers.session_state import session_state_path

    assert session_state_path("/ws", "codex", "sess-1") == (
        "/ws/.agent-state/codex/sessions/sess-1.json"
    )


def test_read_session_state_missing_returns_none(tmp_path):
    from agentcore.drivers.session_state import read_session_state

    assert read_session_state(str(tmp_path), "codex", "nope") is None


def test_write_then_read_roundtrip(tmp_path):
    from agentcore.drivers.session_state import read_session_state, write_session_state

    write_session_state(
        str(tmp_path), "vanilla", "sess-1",
        {"messages": [{"role": "user", "content": "hi"}]},
    )
    assert read_session_state(str(tmp_path), "vanilla", "sess-1") == {
        "messages": [{"role": "user", "content": "hi"}]
    }


def test_read_session_state_corrupt_json_returns_none(tmp_path):
    from agentcore.drivers.session_state import read_session_state, session_state_path

    path = session_state_path(str(tmp_path), "codex", "sess-2")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert read_session_state(str(tmp_path), "codex", "sess-2") is None


def test_read_session_state_non_dict_json_returns_none(tmp_path):
    from agentcore.drivers.session_state import read_session_state, session_state_path

    path = session_state_path(str(tmp_path), "codex", "sess-3")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")
    assert read_session_state(str(tmp_path), "codex", "sess-3") is None


def test_write_session_state_creates_parent_dirs(tmp_path):
    from agentcore.drivers.session_state import session_state_path, write_session_state

    write_session_state(str(tmp_path), "opencode", "sess-4", {"opencode_session_id": "ses_x"})
    assert os.path.isfile(session_state_path(str(tmp_path), "opencode", "sess-4"))


def test_write_session_state_unlinks_existing_file_before_recreating(tmp_path, monkeypatch):
    """Regression (found via live E2E verification against a real hardened
    container, not caught by any unit test): a prior task's write chowns this
    file to the agent uid; root lacks CAP_FOWNER, so chmod-ing that same file
    in place on a later write would raise EPERM ("Operation not permitted").
    write_session_state must unlink before recreating, matching the identical
    fix already used by codex.py's/opencode.py's write_auth_json.
    """
    from pathlib import Path as PathClass

    from agentcore.drivers import session_state as mod

    path = mod.session_state_path(str(tmp_path), "claude-code", "sess-5")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"claude_session_id": "old"}')

    unlink_calls: list[str] = []
    original_unlink = PathClass.unlink

    def spy_unlink(self: PathClass, missing_ok: bool = False) -> None:
        unlink_calls.append(str(self))
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(PathClass, "unlink", spy_unlink)

    mod.write_session_state(str(tmp_path), "claude-code", "sess-5", {"claude_session_id": "new"})

    assert unlink_calls == [path]
    assert mod.read_session_state(str(tmp_path), "claude-code", "sess-5") == {
        "claude_session_id": "new"
    }
