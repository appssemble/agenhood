# services/control_plane/tests/integration/stub_llm/app.py
# Deterministic Anthropic-Messages stub for control-plane integration tests.
#
# Default script (3 turns):
#   turn 0  -> write_file(out.txt, "hello from stub")
#   turn 1  -> done({"value": 42})
#
# Slow script (first-turn delay of 5 s, triggered when system prompt contains
# the word SLOW): same 2-turn conversation but stage 0 sleeps 5 s first.
# This lets the concurrency-cap test submit a second task before the first
# worker finishes.
#
# Header-recording: stores the last x-api-key / Authorization header received
# so tests can verify the decrypted credential was forwarded correctly.
# GET /_test/last_auth_header returns {"auth_header": "..."} or null.
from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request

app = FastAPI()

# Process-global: stores the most recent auth header received from any caller.
# Intentionally simple — the integration test resets it by re-running the task.
_last_auth_header: str | None = None


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
    stage = _count_tool_results(body.get("messages", []))

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
    import json as _json

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
