"""One live vanilla-loop e2e per built-in tool (spec: works-as-expected sweep).

Each case scripts the stub LLM (@@SCRIPT@@) to call one tool, then `done`
with the tool's observed output, and asserts the task completes.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}

ALL_TOOLS = ["read_file", "write_file", "edit_file", "list_files",
             "delete_file", "bash", "python", "web_search", "web_fetch", "web_read"]


async def _run_scripted(app, script: dict, tools: list[str]) -> tuple[str, list[dict]]:
    """Create a vanilla container, run one scripted task, return
    (terminal_status, tool_result_event_payloads)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/containers", headers=_HEADERS,
            json={"name": "tool-sweep",
                  "config": {"driver": "vanilla", "model": "claude-opus-4-7",
                             "tools": tools}},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            ts = await client.post(
                f"/v1/containers/{cid}/tasks", headers=_HEADERS,
                json={"prompt": "@@SCRIPT@@ " + json.dumps(script)},
            )
            assert ts.status_code == 200, ts.text
            tid = ts.json()["task_id"]
            terminal, tool_results = None, []
            sse_headers = {**_HEADERS, "Accept": "text/event-stream"}
            async with client.stream(
                "GET", f"/v1/containers/{cid}/tasks/{tid}/events",
                headers=sse_headers, timeout=120,
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[len("data:"):].strip())
                    if ev["type"] == "tool_result":
                        tool_results.append(ev["payload"])
                    if ev["type"] == "status_change" and ev["payload"].get("to") in (
                        "completed", "failed", "timed_out", "cancelled",
                    ):
                        terminal = ev["payload"]["to"]
                        break
            return terminal, tool_results
        finally:
            await client.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)


CASES = [
    ("write_file", {"turns": [
        {"tool": "write_file", "input": {"path": "a.txt", "content": "hello"}},
        {"done": {"success": True, "output": "wrote"}}]},
     lambda results: results[0]["ok"]),
    ("read_file", {"turns": [
        {"tool": "write_file", "input": {"path": "r.txt", "content": "readme-body"}},
        {"tool": "read_file", "input": {"path": "r.txt"}},
        {"done": {"success": True, "output": "read"}}]},
     lambda results: results[1]["ok"] and "readme-body" in results[1]["content"]),
    ("edit_file", {"turns": [
        {"tool": "write_file", "input": {"path": "e.txt", "content": "old text"}},
        {"tool": "edit_file", "input": {"path": "e.txt", "old_string": "old", "new_string": "new"}},
        {"tool": "read_file", "input": {"path": "e.txt"}},
        {"done": {"success": True, "output": "edited"}}]},
     lambda results: results[2]["ok"] and "new text" in results[2]["content"]),
    ("list_files", {"turns": [
        {"tool": "write_file", "input": {"path": "l.txt", "content": "x"}},
        {"tool": "list_files", "input": {}},
        {"done": {"success": True, "output": "listed"}}]},
     lambda results: results[1]["ok"] and "l.txt" in results[1]["content"]),
    ("delete_file", {"turns": [
        {"tool": "write_file", "input": {"path": "d.txt", "content": "x"}},
        {"tool": "delete_file", "input": {"path": "d.txt"}},
        {"tool": "list_files", "input": {}},
        {"done": {"success": True, "output": "deleted"}}]},
     lambda results: results[1]["ok"] and "d.txt" not in results[2]["content"]),
    ("bash", {"turns": [
        {"tool": "bash", "input": {"command": "echo sweep-bash-ok"}},
        {"done": {"success": True, "output": "ran"}}]},
     lambda results: results[0]["ok"] and "sweep-bash-ok" in results[0]["content"]),
    ("python", {"turns": [
        {"tool": "python", "input": {"code": "print('sweep-py-ok')"}},
        {"done": {"success": True, "output": "ran"}}]},
     lambda results: results[0]["ok"] and "sweep-py-ok" in results[0]["content"]),
    ("web_search", {"turns": [
        {"tool": "web_search", "input": {"query": "agents"}},
        {"done": {"success": True, "output": "searched"}}]},
     lambda results: results[0]["ok"] and "stub snippet about agents" in results[0]["content"]),
    ("web_fetch", {"turns": [
        {"tool": "web_fetch", "input": {"url": "http://stub-llm-test:8080/page"}},
        {"done": {"success": True, "output": "fetched"}}]},
     lambda results: results[0]["ok"] and "Stub Page" in results[0]["content"]),
    ("web_read", {"turns": [
        {"tool": "web_read", "input": {"url": "http://stub-llm-test:8080/page"}},
        {"done": {"success": True, "output": "read"}}]},
     lambda results: results[0]["ok"] and "Stub Page" in results[0]["content"]),
]


@pytest.mark.parametrize("tool_name,script,check", CASES, ids=[c[0] for c in CASES])
async def test_builtin_tool_end_to_end(seeded_app, tool_name, script, check):
    terminal, results = await _run_scripted(seeded_app, script, ALL_TOOLS)
    assert terminal == "completed", f"{tool_name}: task ended {terminal}"
    assert results, f"{tool_name}: no tool_result events"
    assert check(results), f"{tool_name}: assertion failed on {results}"
