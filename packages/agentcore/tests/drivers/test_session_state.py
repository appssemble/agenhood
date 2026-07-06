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
