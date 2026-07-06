import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_codex_event_types_registered():
    from agentcore.events import EVENT_TYPES

    assert "codex_event" in EVENT_TYPES
    assert "codex_stdout" in EVENT_TYPES


def test_codex_event_builders():
    from agentcore import events

    assert events.codex_stdout("hi") == {"line": "hi"}
    assert events.codex_event({"type": "turn.completed"}) == {"raw": {"type": "turn.completed"}}


def test_model_arg_strips_openai_prefix():
    from agentcore.drivers.codex import model_arg

    assert model_arg("openai/gpt-5-codex") == "gpt-5-codex"
    assert model_arg("gpt-5-codex") == "gpt-5-codex"


def test_codex_home_under_workspace():
    from agentcore.drivers.codex import codex_home

    assert codex_home("/workspace") == "/workspace/.agent-state/codex"


def test_build_command_reads_prompt_from_stdin():
    from agentcore.drivers.codex import build_command

    cmd = build_command(workspace="/ws", model="gpt-5-codex")
    assert cmd == [
        "codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral",
        "-C", "/ws", "-m", "gpt-5-codex",
        "--dangerously-bypass-approvals-and-sandbox", "-",
    ]


def test_build_env_api_key_sets_codex_api_key():
    from agentcore.drivers.codex import build_env

    env = build_env({}, credential="sk-123", credential_kind="api_key", codex_home="/ws/.agent-state/codex")  # noqa: E501
    assert env["CODEX_API_KEY"] == "sk-123"
    assert env["CODEX_HOME"] == "/ws/.agent-state/codex"
    assert env["HOME"] == "/ws/.agent-state/codex"


def test_build_env_oauth_sets_no_api_key():
    from agentcore.drivers.codex import build_env

    env = build_env({}, credential="tok", credential_kind="oauth_subscription", codex_home="/ws/.agent-state/codex")  # noqa: E501
    assert "CODEX_API_KEY" not in env
    assert env["CODEX_HOME"] == "/ws/.agent-state/codex"


def test_write_auth_json_shape_and_mode(tmp_path):
    from agentcore.drivers.codex import write_auth_json

    home = tmp_path / "codex"
    path = write_auth_json(
        str(home),
        access_token="acc",
        refresh_token="ref",
        account_id="acct-1",
        id_token=None,
        last_refresh="2026-06-08T00:00:00+00:00",
    )
    data = json.loads(Path(path).read_text())
    assert data["OPENAI_API_KEY"] is None
    assert data["tokens"] == {"access_token": "acc", "refresh_token": "ref", "account_id": "acct-1"}
    assert data["last_refresh"] == "2026-06-08T00:00:00+00:00"
    assert "id_token" not in data["tokens"]
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_write_auth_json_recreates_existing_file(tmp_path):
    """A 2nd+ oauth task rewrites auth.json. The shim runs as root without
    CAP_FOWNER, so it cannot chmod a file a prior task chowned to the agent uid.
    write_auth_json must recreate the file (fresh, root-owned before chmod), not
    truncate in place. A held-open fd pins the old inode so a recreate yields a
    new st_ino."""
    from agentcore.drivers.codex import write_auth_json

    home = str(tmp_path / "codex")
    path = write_auth_json(home, access_token="a1", refresh_token="r1",
                           account_id="x", id_token=None, last_refresh="t1")
    with open(path) as held:
        old_ino = os.fstat(held.fileno()).st_ino
        write_auth_json(home, access_token="a2", refresh_token="r2",
                        account_id="x", id_token=None, last_refresh="t2")
        new_ino = os.stat(path).st_ino
    assert new_ino != old_ino, "auth.json was truncated in place, not recreated"
    assert json.loads(Path(path).read_text())["tokens"]["access_token"] == "a2"
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_write_auth_json_includes_id_token_when_present(tmp_path):
    from agentcore.drivers.codex import write_auth_json

    path = write_auth_json(
        str(tmp_path / "codex"),
        access_token="acc", refresh_token="ref", account_id="acct",
        id_token="idtok", last_refresh="2026-06-08T00:00:00+00:00",
    )
    data = json.loads(Path(path).read_text())
    assert data["tokens"]["id_token"] == "idtok"


def test_parse_codex_line_classifies():
    from agentcore.drivers.codex import parse_codex_line

    assert parse_codex_line("") == ("ignore", None)
    assert parse_codex_line("   ") == ("ignore", None)
    assert parse_codex_line('{"type":"turn.completed"}') == ("event", {"type": "turn.completed"})
    assert parse_codex_line("not json") == ("stdout", "not json")
    assert parse_codex_line("{bad") == ("stdout", "{bad")


def test_event_text_returns_agent_message():
    from agentcore.drivers.codex import event_text

    ev = {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}
    assert event_text(ev) == "done"
    assert event_text({"type": "item.completed", "item": {"type": "reasoning", "text": "x"}}) is None  # noqa: E501
    assert event_text({"type": "turn.completed"}) is None


def test_event_usage_from_turn_completed():
    from agentcore.drivers.codex import event_usage

    ev = {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20,
                                              "cached_input_tokens": 90, "reasoning_output_tokens": 5}}  # noqa: E501
    assert event_usage(ev) == (100, 20)
    assert event_usage({"type": "turn.completed", "usage": {"input_tokens": True, "output_tokens": 1}}) is None  # noqa: E501
    assert event_usage({"type": "item.completed"}) is None


def test_event_error_messages():
    from agentcore.drivers.codex import event_error

    assert event_error({"type": "turn.failed", "error": {"message": "boom"}}) == "boom"
    assert event_error({"type": "error", "message": "nope"}) == "nope"
    assert event_error({"type": "turn.completed"}) is None


def test_codex_registered_via_package_import():
    import importlib

    import agentcore.drivers as drivers_pkg
    importlib.reload(drivers_pkg)
    from agentcore.drivers.base import DRIVERS

    assert "codex" in DRIVERS


# ---------------------------------------------------------------------------
# Task 5: privsep — .agent-state home + allowlisted env
# ---------------------------------------------------------------------------

def test_codex_home_is_under_agent_state():
    from agentcore.drivers import codex
    assert codex.codex_home("/workspace").endswith("/.agent-state/codex")


def test_codex_skills_dir_is_under_agent_state():
    from agentcore.drivers import codex
    assert "/.agent-state/codex/" in codex.skills_dir("/workspace")


def test_codex_build_env_starts_from_allowlist(monkeypatch):
    monkeypatch.setenv("SHIM_TOKEN", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    from agentcore import sandbox
    from agentcore.drivers import codex
    env = codex.build_env(
        sandbox.build_child_env(),
        credential="k",
        credential_kind="api_key",
        codex_home="/workspace/.agent-state/codex",
    )
    assert "SHIM_TOKEN" not in env
    assert env["CODEX_API_KEY"] == "k"
    assert env["CODEX_HOME"] == "/workspace/.agent-state/codex"


# ---------------------------------------------------------------------------
# Task 4: driver sessions — ephemeral/resume command shape + thread id parsing
# ---------------------------------------------------------------------------

def test_build_command_ephemeral_true_by_default_unchanged():
    from agentcore.drivers.codex import build_command

    cmd = build_command(workspace="/ws", model="gpt-5-codex")
    assert cmd == [
        "codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral",
        "-C", "/ws", "-m", "gpt-5-codex",
        "--dangerously-bypass-approvals-and-sandbox", "-",
    ]


def test_build_command_ephemeral_false_drops_the_flag():
    from agentcore.drivers.codex import build_command

    cmd = build_command(workspace="/ws", model="gpt-5-codex", ephemeral=False)
    assert "--ephemeral" not in cmd
    assert cmd == [
        "codex", "exec", "--json", "--skip-git-repo-check",
        "-C", "/ws", "-m", "gpt-5-codex",
        "--dangerously-bypass-approvals-and-sandbox", "-",
    ]


def test_build_resume_command():
    from agentcore.drivers.codex import build_resume_command

    cmd = build_resume_command(model="gpt-5-codex", thread_id="019f3753-thread")
    # Verified live against the installed codex CLI: `codex exec resume` has no
    # -C/--ephemeral flags (the resumed session's cwd/persistence are implicit).
    assert cmd == [
        "codex", "exec", "resume", "--json", "--skip-git-repo-check",
        "-m", "gpt-5-codex", "--dangerously-bypass-approvals-and-sandbox",
        "019f3753-thread", "-",
    ]


def test_event_thread_id_extracts_from_thread_started():
    from agentcore.drivers.codex import event_thread_id

    assert event_thread_id({"type": "thread.started", "thread_id": "t-1"}) == "t-1"


def test_event_thread_id_ignores_other_event_types():
    from agentcore.drivers.codex import event_thread_id

    assert event_thread_id({"type": "turn.completed", "thread_id": "t-1"}) is None
    assert event_thread_id({"type": "thread.started"}) is None
    assert event_thread_id({"type": "thread.started", "thread_id": 5}) is None
