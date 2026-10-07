import json
from pathlib import Path

import pytest

from agentcore.drivers.codex_events import ExecEventTranslator

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "codex_streams"


def note(method, **params):
    return {"method": method, "params": params}


def test_thread_started():
    assert ExecEventTranslator().thread_started("thr_1") == {
        "type": "thread.started", "thread_id": "thr_1",
    }


def test_agent_message_only_on_completion():
    tr = ExecEventTranslator()
    item = {"type": "agentMessage", "id": "msg_a", "text": "", "phase": "final_answer"}
    assert tr.translate(note("item/started", item=item)) == []
    done = {**item, "text": "OK"}
    assert tr.translate(note("item/completed", item=done)) == [
        {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "OK"}}
    ]


def test_command_execution_started_and_completed():
    tr = ExecEventTranslator()
    started = {"type": "commandExecution", "id": "exec-1", "command": "/bin/bash -lc 'echo hello'",
               "status": "inProgress", "aggregatedOutput": None, "exitCode": None,
               "cwd": "/w", "commandActions": []}
    done = {**started, "status": "completed", "aggregatedOutput": "hello\n", "exitCode": 0}
    assert tr.translate(note("item/started", item=started)) == [{"type": "item.started", "item": {
        "id": "item_0", "type": "command_execution", "command": "/bin/bash -lc 'echo hello'",
        "aggregated_output": "", "exit_code": None, "status": "in_progress"}}]
    assert tr.translate(note("item/completed", item=done)) == [{"type": "item.completed", "item": {
        "id": "item_0", "type": "command_execution", "command": "/bin/bash -lc 'echo hello'",
        "aggregated_output": "hello\n", "exit_code": 0, "status": "completed"}}]


def test_file_change_keeps_path_and_kind():
    tr = ExecEventTranslator()
    item = {"type": "fileChange", "id": "exec-2", "status": "completed",
            "changes": [{"path": "/w/note.txt", "kind": {"type": "add"}, "diff": "hi\n"}]}
    assert tr.translate(note("item/completed", item=item)) == [{"type": "item.completed", "item": {
        "id": "item_0", "type": "file_change",
        "changes": [{"path": "/w/note.txt", "kind": "add"}], "status": "completed"}}]


def test_web_search_keeps_codex_id_and_maps_the_action():
    tr = ExecEventTranslator()
    started = {"type": "webSearch", "id": "ws-1", "query": "", "action": None, "results": None}
    done = {"type": "webSearch", "id": "ws-1", "query": "python",
            "action": {"type": "openPage", "url": "https://python.org", "query": None},
            "results": [{"title": "Python"}]}
    assert tr.translate(note("item/started", item=started)) == [{"type": "item.started", "item": {
        "id": "ws-1", "type": "web_search", "query": "", "action": {"type": "other"}}}]
    assert tr.translate(note("item/completed", item=done)) == [{"type": "item.completed", "item": {
        "id": "ws-1", "type": "web_search", "query": "python",
        "action": {"type": "open_page", "url": "https://python.org"},
        "results": [{"title": "Python"}]}}]


def test_reasoning_needs_a_summary():
    tr = ExecEventTranslator()
    empty = {"type": "reasoning", "id": "rs_1", "summary": [], "content": []}
    assert tr.translate(note("item/completed", item=empty)) == []
    full = {"type": "reasoning", "id": "rs_2", "summary": ["**Plan**", "**Check**"], "content": []}
    assert tr.translate(note("item/completed", item=full)) == [{"type": "item.completed", "item": {
        "id": "item_0", "type": "reasoning", "text": "**Plan**\n\n**Check**"}}]


def test_mcp_tool_call():
    tr = ExecEventTranslator()
    item = {"type": "mcpToolCall", "id": "mcp-1", "server": "docs", "tool": "search",
            "arguments": {"q": "x"}, "result": {"content": []}, "error": None,
            "status": "completed"}
    assert tr.translate(note("item/completed", item=item)) == [{"type": "item.completed", "item": {
        "id": "item_0", "type": "mcp_tool_call", "server": "docs", "tool": "search",
        "arguments": {"q": "x"}, "result": {"content": []}, "error": None,
        "status": "completed"}}]


def test_user_messages_and_unknown_notifications_are_dropped():
    tr = ExecEventTranslator()
    user = {"type": "userMessage", "id": "u1", "content": []}
    assert tr.translate(note("item/completed", item=user)) == []
    assert tr.translate(note("configWarning", summary="bubblewrap")) == []
    assert tr.translate(note("thread/status/changed", status={"type": "idle"})) == []


def test_warning_becomes_an_error_item():
    tr = ExecEventTranslator()
    assert tr.translate(note("warning", message="fallback metadata")) == [
        {"type": "item.completed", "item": {"id": "item_0", "type": "error",
                                            "message": "fallback metadata"}}
    ]


def test_turn_completed_sums_usage_per_request():
    tr = ExecEventTranslator()
    for last in ({"inputTokens": 10461, "cachedInputTokens": 10240, "outputTokens": 58},
                 {"inputTokens": 10544, "cachedInputTokens": 10240, "outputTokens": 5}):
        assert tr.translate(note("thread/tokenUsage/updated", tokenUsage={"last": last})) == []
    out = tr.translate(note("turn/completed", turn={"status": "completed", "error": None}))
    assert out == [{"type": "turn.completed", "usage": {
        "input_tokens": 21005, "cached_input_tokens": 20480, "cache_write_input_tokens": 0,
        "output_tokens": 63, "reasoning_output_tokens": 0}}]


def test_failed_turn_and_error():
    tr = ExecEventTranslator()
    assert tr.translate(note("error", error={"message": "bad model"}, willRetry=False)) == [
        {"type": "error", "message": "bad model"}
    ]
    assert tr.translate(note("turn/completed", turn={"status": "failed",
                                                     "error": {"message": "bad model"}})) == [
        {"type": "turn.failed", "error": {"message": "bad model"}}
    ]
    assert tr.translate(note("turn/completed", turn={"status": "interrupted"})) == []


def _shape(event):
    item = event.get("item") or {}
    return (event["type"], item.get("type"), tuple(sorted(event)), tuple(sorted(item)),
            item.get("status"))


def _translate_recording(messages):
    tr = ExecEventTranslator()
    out = []
    for msg in messages:
        result = msg.get("result")
        if "id" in msg and isinstance(result, dict) and "thread" in result:
            out.append(tr.thread_started(result["thread"]["id"]))
        elif "method" in msg and "id" not in msg:
            out.extend(tr.translate(msg))
    return out


def _final_text(events):
    texts = [e["item"]["text"] for e in events
             if e["type"] == "item.completed" and e["item"]["type"] == "agent_message"
             and e["item"]["text"]]
    return texts[-1] if texts else None


@pytest.mark.parametrize("case", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_recorded_app_server_stream_matches_the_exec_shapes(case):
    recording = json.loads((FIXTURES / f"{case}.json").read_text())
    exec_events = [e for e in recording["exec"] if "type" in e]
    translated = _translate_recording(recording["app_server"])

    assert {_shape(e) for e in translated} <= {_shape(e) for e in exec_events}
    assert translated[0]["type"] == exec_events[0]["type"] == "thread.started"
    assert translated[-1]["type"] == exec_events[-1]["type"]
    assert _final_text(translated) == _final_text(exec_events)
    if translated[-1]["type"] == "turn.completed":
        assert sorted(translated[-1]["usage"]) == sorted(exec_events[-1]["usage"])
