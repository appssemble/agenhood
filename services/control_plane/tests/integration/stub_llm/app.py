# services/control_plane/tests/integration/stub_llm/app.py
# Deterministic Anthropic-Messages stub for control-plane integration tests.
#
# Two modes on POST /v1/messages:
#   - legacy (default 3-turn script, no @@SCRIPT@@ marker in the first user
#     message): write_file(out.txt, "hello from stub") -> done({"value": 42}).
#     Several existing tests depend on this fixed script verbatim.
#   - scripted (@@SCRIPT@@ {json} present in the first user message): replay
#     the script's turns, keyed by the number of tool_result blocks already
#     in the conversation (mirrors deploy/stub_llm/app.py).
#
# Slow script (first-turn delay of 5 s, triggered when system prompt contains
# the word SLOW): same 2-turn conversation but stage 0 sleeps 5 s first.
# This lets the concurrency-cap test submit a second task before the first
# worker finishes.
#
# Header-recording: stores the last x-api-key / Authorization header received
# so tests can verify the decrypted credential was forwarded correctly.
# GET /_test/last_auth_header returns {"auth_header": "..."} or null.
#
# GET /search and GET /page: SearXNG-shaped search results and a simple HTML
# page, so the web_search/web_fetch built-in tools are testable end-to-end.
from __future__ import annotations

import asyncio
import json as _json
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI()

# Process-global: stores the most recent auth header received from any caller.
# Intentionally simple — the integration test resets it by re-running the task.
_last_auth_header: str | None = None

SCRIPT_MARKER = "@@SCRIPT@@"


def extract_script(content: Any) -> dict | None:
    """Pull the @@SCRIPT@@ {json} object out of a user message, else None."""
    if not isinstance(content, str) or SCRIPT_MARKER not in content:
        return None
    raw = content.split(SCRIPT_MARKER, 1)[1].strip()
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        return None


def _first_user_text(messages: list) -> Any:
    for m in messages:
        if m.get("role") == "user":
            return m.get("content")
    return None


def _turn_to_content(turn: dict) -> list[dict]:
    blocks: list[dict] = []
    if isinstance(turn.get("text"), str):
        blocks.append({"type": "text", "text": turn["text"]})
    if "done" in turn:
        blocks.append({"type": "tool_use", "id": "tu_done", "name": "done",
                       "input": turn["done"]})
    elif turn.get("tool"):
        blocks.append({"type": "tool_use", "id": f"tu_{turn['tool']}",
                       "name": turn["tool"], "input": turn.get("input", {})})
    if not blocks:  # empty turn -> emit a no-op text so the loop still advances
        blocks.append({"type": "text", "text": ""})
    return blocks


def _count_tool_results(messages: list) -> int:
    n = 0
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for block in m["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    n += 1
    return n


def _is_slow(body: dict) -> bool:
    """Return True if any system-level content contains the word SLOW."""
    for m in body.get("messages", []):
        if isinstance(m.get("content"), str) and "SLOW" in m["content"]:
            return True
    system = body.get("system", "")
    if isinstance(system, str) and "SLOW" in system:
        return True
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and "SLOW" in block.get("text", ""):
                return True
    return False


@app.post("/v1/messages")
async def messages(req: Request) -> dict:
    global _last_auth_header
    # Record the auth header so tests can verify decrypted credentials arrive.
    _last_auth_header = (
        req.headers.get("x-api-key") or req.headers.get("authorization")
    )

    body = await req.json()
    msgs = body.get("messages", [])
    script = extract_script(_first_user_text(msgs))

    if script is None:
        stage = _count_tool_results(msgs)

        if stage == 0 and _is_slow(body):
            await asyncio.sleep(5)

        if stage == 0:
            content = [
                {"type": "tool_use", "id": "tu_write", "name": "write_file",
                 "input": {"path": "out.txt", "content": "hello from stub"}},
            ]
        else:
            content = [
                {"type": "tool_use", "id": "tu_done", "name": "done",
                 "input": {"success": True, "output": {"value": 42}}},
            ]

        return {
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", "stub"),
            "stop_reason": "tool_use",
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    stage = _count_tool_results(msgs)
    turns = script.get("turns", [])
    if stage < len(turns):
        content = _turn_to_content(turns[stage])
    else:
        # Past the script -> finish so the loop cannot hang.
        content = [{"type": "tool_use", "id": "tu_done", "name": "done",
                    "input": {"success": True, "output": "done"}}]

    return {
        "id": "msg_stub",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "stub"),
        "stop_reason": "tool_use",
        "content": content,
        "usage": script.get("usage", {"input_tokens": 1, "output_tokens": 1}),
    }


@app.get("/_test/last_auth_header")
async def last_auth_header() -> dict:
    """Return the most recent auth header seen by POST /v1/messages.

    Used by the credential-attach integration test to verify the decrypted
    key reached the LLM without being persisted in the DB.
    """
    return {"auth_header": _last_auth_header}


def _count_tool_messages(messages: list) -> int:
    return sum(1 for m in messages if m.get("role") == "tool")


@app.post("/v1/chat/completions")
async def chat_completions(req: Request) -> dict:
    """OpenAI-format twin of /v1/messages: write_file(out.txt) then done."""
    global _last_auth_header
    _last_auth_header = req.headers.get("authorization")

    body = await req.json()

    stage = _count_tool_messages(body.get("messages", []))
    if stage == 0:
        tool_calls = [{
            "id": "call_write", "type": "function",
            "function": {"name": "write_file",
                         "arguments": _json.dumps(
                             {"path": "out.txt", "content": "hello from stub"})},
        }]
    else:
        tool_calls = [{
            "id": "call_done", "type": "function",
            "function": {"name": "done",
                         "arguments": _json.dumps(
                             {"success": True, "output": {"value": 42}})},
        }]

    return {
        "id": "chatcmpl_stub",
        "object": "chat.completion",
        "model": body.get("model", "stub"),
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None,
                        "tool_calls": tool_calls},
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


@app.get("/search")
async def search(q: str = "", format: str = "json") -> dict:
    return {"results": [
        {"title": f"Result for {q}", "url": "http://stub-llm-test:8080/page",
         "content": f"stub snippet about {q}"},
    ]}


@app.get("/page")
async def page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<html><head><title>Stub Page</title></head><body>"
        "<article><h1>Stub Page</h1><p>This is the stub page body for "
        "fetch tests. It has enough prose to satisfy readability "
        "extraction heuristics used by trafilatura in the web_fetch tool. "
        "The quick brown fox jumps over the lazy dog repeatedly.</p>"
        "</article></body></html>"
    )
