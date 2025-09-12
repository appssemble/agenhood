# deploy/stub_llm/app.py
# A deterministic Anthropic-Messages stub for integration tests.
# Two modes:
#   - legacy: no @@SCRIPT@@ in the first user message -> fixed 3-stage script.
#   - scripted: @@SCRIPT@@ {json} in the first user message -> replay the script,
#     keyed by the number of tool_result blocks already in the conversation.
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI()

SCRIPT_MARKER = "@@SCRIPT@@"


def extract_script(content: Any) -> dict | None:
    """Pull the @@SCRIPT@@ {json} object out of a user message, else None."""
    if not isinstance(content, str) or SCRIPT_MARKER not in content:
        return None
    raw = content.split(SCRIPT_MARKER, 1)[1].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _count_tool_results(messages) -> int:
    n = 0
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for block in m["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    n += 1
    return n


def _first_user_text(messages) -> Any:
    for m in messages:
        if m.get("role") == "user":
            return m.get("content")
    return None


def _legacy_content(stage: int):
    if stage == 0:
        return [
            {"type": "text", "text": "Searching the web."},
            {"type": "tool_use", "id": "tu_search", "name": "web_search",
             "input": {"query": "self-hosted email marketing"}},
        ]
    if stage == 1:
        return [
            {"type": "tool_use", "id": "tu_write", "name": "write_file",
             "input": {"path": "report.md",
                       "content": "# Email Platforms\nListmonk, Mautic."}},
        ]
    return [
        {"type": "tool_use", "id": "tu_done", "name": "done",
         "input": {"success": True,
                   "output": {"report_path": "report.md",
                              "platforms": ["Listmonk", "Mautic"]}}},
    ]


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


@app.post("/v1/messages")
async def messages(req: Request):
    body = await req.json()
    msgs = body.get("messages", [])
    script = extract_script(_first_user_text(msgs))

    if script is None:
        content = _legacy_content(_count_tool_results(msgs))
        usage = {"input_tokens": 100, "output_tokens": 50}
        return _envelope(body, content, usage)

    delay_ms = int(script.get("delay_ms") or 0)
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000.0)

    if script.get("malformed"):
        return PlainTextResponse("this is not json", status_code=200)

    http_error = script.get("http_error")
    if http_error:
        return JSONResponse(
            status_code=int(http_error.get("status", 500)),
            content={"type": "error",
                     "error": {"type": "overloaded_error", "message": "stubbed"}},
        )

    stage = _count_tool_results(msgs)
    usage = script.get("usage", {"input_tokens": 1, "output_tokens": 1})

    if script.get("never_done"):
        # Force the vanilla loop to spin until max_iterations: always call a
        # real, side-effect-free tool (list_files) and never `done`.
        content = [{"type": "tool_use", "id": "tu_loop", "name": "list_files",
                    "input": {}}]
        return _envelope(body, content, usage)

    turns = script.get("turns", [])
    if stage < len(turns):
        content = _turn_to_content(turns[stage])
    else:
        # Past the script -> finish so the loop cannot hang.
        content = [{"type": "tool_use", "id": "tu_done", "name": "done",
                    "input": {"success": True, "output": "done"}}]
    return _envelope(body, content, usage)


def _envelope(body, content, usage):
    return {
        "id": "msg_stub", "type": "message", "role": "assistant",
        "model": body.get("model", "stub"), "stop_reason": "tool_use",
        "content": content, "usage": usage,
    }
