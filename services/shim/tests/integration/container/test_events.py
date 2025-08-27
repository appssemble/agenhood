# services/shim/tests/integration/container/test_events.py
import json

import httpx
import pytest

from . import scripting as sc
from .conftest import BASE, TOKEN

pytestmark = pytest.mark.integration

HDR = {"Authorization": f"Bearer {TOKEN}"}


def _sse_types(text):
    return [json.loads(l[len("data: "):])["type"]
            for l in text.splitlines() if l.startswith("data: ")]


def test_replay_after_completion_orders_and_terminates(client):
    tid = "tsk_evt_replay"
    body = sc.task_body(tid, "vanilla",
                        turns=[{"text": "hi", "done": {"success": True,
                                                       "output": "ok"}}])
    # Disable git snapshots so no 'git' events appear after status_change,
    # letting us assert the terminal-once contract cleanly.
    body["git_snapshots"] = False
    client.post("/tasks", json=body)
    sc.poll_terminal(client, tid)
    sse = httpx.get(f"{BASE}/tasks/{tid}/events", headers=HDR, timeout=10)
    types = _sse_types(sse.text)
    assert types[0] == "task_started"
    assert types[-1] == "status_change"
    # exactly one terminal status_change
    assert types.count("status_change") == 1


def test_after_seq_resumes(client):
    tid = "tsk_evt_after"
    body = sc.task_body(tid, "vanilla",
                        turns=[{"done": {"success": True, "output": "ok"}}])
    body["git_snapshots"] = False
    client.post("/tasks", json=body)
    sc.poll_terminal(client, tid)
    full = _sse_types(httpx.get(f"{BASE}/tasks/{tid}/events",
                                headers=HDR, timeout=10).text)
    partial = httpx.get(f"{BASE}/tasks/{tid}/events",
                        params={"after_seq": 1}, headers=HDR, timeout=10)
    # Strictly fewer events than the full replay (seq 1 skipped).
    assert len(_sse_types(partial.text)) < len(full)


def test_tool_events_appear_in_sse(client):
    """tool_call and tool_result must appear in the SSE stream for a tool turn.

    Restored from deleted test_container_e2e.py — locks the behavioral contract
    that tool execution surfaces as discrete typed events in the event stream.
    """
    tid = "tsk_evt_tool"
    body = sc.task_body(
        tid, "vanilla",
        turns=[
            {"tool": "write_file", "input": {"path": "sse_tool.md", "content": "x"}},
            {"done": {"success": True, "output": "ok"}},
        ],
    )
    body["git_snapshots"] = False
    client.post("/tasks", json=body)
    sc.poll_terminal(client, tid)
    sse = httpx.get(f"{BASE}/tasks/{tid}/events", headers=HDR, timeout=10)
    types = _sse_types(sse.text)
    assert "tool_call" in types, f"tool_call missing from SSE stream; got {types}"
    assert "tool_result" in types, f"tool_result missing from SSE stream; got {types}"


def test_missing_task_events_404(client):
    r = client.get("/tasks/nope/events")
    assert r.status_code == 404
