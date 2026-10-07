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
# Thread id parsing
# ---------------------------------------------------------------------------


def test_event_thread_id_extracts_from_thread_started():
    from agentcore.drivers.codex import event_thread_id

    assert event_thread_id({"type": "thread.started", "thread_id": "t-1"}) == "t-1"


def test_event_thread_id_ignores_other_event_types():
    from agentcore.drivers.codex import event_thread_id

    assert event_thread_id({"type": "turn.completed", "thread_id": "t-1"}) is None
    assert event_thread_id({"type": "thread.started"}) is None
    assert event_thread_id({"type": "thread.started", "thread_id": 5}) is None


# ---------------------------------------------------------------------------
# Stale AGENTS.md cleanup and tool flags
# ---------------------------------------------------------------------------


def test_remove_stale_agents_md_deletes_file_left_by_older_driver(tmp_path):
    """Driver versions before 2026-09 wrote the system prompt to
    $CODEX_HOME/AGENTS.md on a persistent volume; a survivor would double the
    prompt next to developer_instructions."""
    import pathlib

    from agentcore.drivers.codex import codex_home, remove_stale_agents_md

    stale = pathlib.Path(codex_home(str(tmp_path))) / "AGENTS.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old prompt")
    remove_stale_agents_md(str(tmp_path))
    assert not stale.exists()
    remove_stale_agents_md(str(tmp_path))  # absent → no error


def _config_overrides(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "-c"]


SIDE_CHANNELS = [
    "features.plugins=false", "features.apps=false",
    "analytics.enabled=false", "otel.exporter=none",
]
ALL_TOOLS_OFF = [
    "web_search=disabled",
    "features.image_generation=false", "features.view_image=false",
    "features.multi_agent=false", "features.goals=false",
]


def test_tool_args_all_off():
    from agentcore.drivers.codex import tool_args

    assert _config_overrides(tool_args([]) + ["x"]) == ALL_TOOLS_OFF


def test_tool_args_all_on():
    from agentcore.drivers.codex import CODEX_TOOLS, tool_args

    assert _config_overrides(tool_args([t.name for t in CODEX_TOOLS]) + ["x"]) == [
        "features.image_generation=true", "features.view_image=true",
        "features.multi_agent=true", "features.goals=true",
    ]


def test_tool_args_ignores_unknown_names():
    from agentcore.drivers.codex import tool_args

    assert tool_args(["bash"]) == tool_args([])


# ---------------------------------------------------------------------------
# Progress updates: every message is a {"progress", "result"} envelope
# ---------------------------------------------------------------------------

USER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["total"],
    "properties": {"total": {"type": "number"}},
}


def test_progress_envelope_wraps_a_structured_schema():
    from agentcore.drivers.codex import progress_envelope_schema

    env = progress_envelope_schema(USER_SCHEMA)
    assert env["required"] == ["progress", "result"]
    assert env["properties"]["result"] == {"anyOf": [USER_SCHEMA, {"type": "null"}]}


def test_progress_envelope_wraps_text_as_a_string():
    from agentcore.drivers.codex import progress_envelope_schema

    env = progress_envelope_schema(None)
    assert env["properties"]["result"] == {"type": ["string", "null"]}


def test_progress_envelope_is_native_compatible_when_the_schema_is():
    from agentcore.drivers.codex import progress_envelope_schema
    from agentcore.structured_output import native_subset_compatible

    assert native_subset_compatible(progress_envelope_schema(USER_SCHEMA))
    assert native_subset_compatible(progress_envelope_schema(None))


def test_split_envelope_reads_a_progress_message():
    from agentcore.drivers.codex import split_envelope

    assert split_envelope('{"progress":"Vou ler o CSV.","result":null}') == ("Vou ler o CSV.", None)


def test_split_envelope_reads_a_final_answer():
    from agentcore.drivers.codex import split_envelope

    assert split_envelope('{"progress":null,"result":{"total":3}}') == (None, {"total": 3})


def test_split_envelope_returns_none_for_plain_text():
    from agentcore.drivers.codex import split_envelope

    assert split_envelope("All done.") is None
    assert split_envelope('{"total":3}') is None


def test_developer_instructions_append_the_progress_rules():
    from agentcore.drivers.codex import PROGRESS_INSTRUCTIONS, developer_instructions

    assert developer_instructions("Be brief.", progress_updates=False) == "Be brief."
    out = developer_instructions("Be brief.", progress_updates=True)
    assert out.startswith("Be brief.")
    assert out.endswith(PROGRESS_INSTRUCTIONS)
    assert developer_instructions("", progress_updates=True) == PROGRESS_INSTRUCTIONS


def test_progress_rules_ask_for_an_initial_update_even_without_tools():
    from agentcore.drivers.codex import PROGRESS_INSTRUCTIONS

    assert "first message is always a progress update" in PROGRESS_INSTRUCTIONS
    assert "even when you can answer without tools" in PROGRESS_INSTRUCTIONS


# ---------------------------------------------------------------------------
# App-server command and request builders
# ---------------------------------------------------------------------------


def test_app_server_command_carries_side_channel_and_tool_overrides():
    from agentcore.drivers.codex import SIDE_CHANNEL_OVERRIDES, build_app_server_command

    cmd = build_app_server_command(tools=["goals"])
    assert cmd[:2] == ["codex", "app-server"]
    for override in SIDE_CHANNEL_OVERRIDES:
        assert cmd[cmd.index(override) - 1] == "-c"
    assert "features.goals=true" in cmd
    assert "web_search=disabled" in cmd


def test_thread_start_params():
    from agentcore.drivers.codex import thread_start_params

    assert thread_start_params(workspace="/w", model="gpt-5.6-sol", instructions="Be brief.") == {
        "model": "gpt-5.6-sol", "cwd": "/w", "ephemeral": False,
        "approvalPolicy": "never", "sandbox": "danger-full-access",
        "developerInstructions": "Be brief.",
    }
    assert "developerInstructions" not in thread_start_params(
        workspace="/w", model="m", instructions="")


def test_thread_resume_params():
    from agentcore.drivers.codex import thread_resume_params

    assert thread_resume_params(thread_id="thr_1", workspace="/w", model="m",
                                instructions="Be brief.") == {
        "threadId": "thr_1", "model": "m", "cwd": "/w",
        "approvalPolicy": "never", "sandbox": "danger-full-access",
        "developerInstructions": "Be brief.",
    }


def test_turn_start_params():
    from agentcore.drivers.codex import turn_start_params

    assert turn_start_params(thread_id="thr_1", prompt="hi", effort=None,
                             reasoning_summary=False, output_schema=None) == {
        "threadId": "thr_1", "input": [{"type": "text", "text": "hi"}],
    }
    schema = {"type": "object"}
    full = turn_start_params(thread_id="thr_1", prompt="hi", effort="high",
                             reasoning_summary=True, output_schema=schema)
    assert full["effort"] == "high"
    assert full["summary"] == "auto"
    assert full["outputSchema"] == schema


def test_native_output_schema():
    from agentcore.drivers.codex import native_output_schema, progress_envelope_schema

    strict = {"type": "object", "properties": {"a": {"type": "string"}},
              "required": ["a"], "additionalProperties": False}
    assert native_output_schema(None, progress_updates=False) is None
    assert native_output_schema(strict, progress_updates=False) == strict
    assert native_output_schema(None, progress_updates=True) == progress_envelope_schema(None)
    assert native_output_schema({"type": "array", "items": {"type": "string"}},
                                progress_updates=False) is None


def test_codex_config_holds_only_mcp_servers(tmp_path):
    from agentcore.drivers.codex import codex_config_path, write_codex_config

    assert write_codex_config(str(tmp_path), []) is None
    assert not Path(codex_config_path(str(tmp_path))).exists()
