"""OpenAI Chat Completions adapter satisfying the LLMClient protocol.

Translates the vanilla loop's canonical Anthropic-style content blocks to the
chat-completions wire format and back. Serves native OpenAI models and
OpenAI-compatible gateways (opencode Zen Go's glm/kimi/mimo/deepseek families).
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from agentcore.llm.base import LLMResponse

DEFAULT_BASE_URL = "https://api.openai.com/v1"

_FINISH_TO_STOP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}


def _content_to_str(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content)


def _to_openai_messages(
    system: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            # List-form user turns carry tool_results; any other block is
            # forwarded as user text.
            texts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": _content_to_str(block.get("content", "")),
                    })
                else:
                    texts.append(_content_to_str(block))
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        else:  # assistant
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue
            text = "\n".join(b["text"] for b in content if b.get("type") == "text")
            tool_calls = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"],
                              "arguments": json.dumps(b.get("input", {}))}}
                for b in content if b.get("type") == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
    return out


def _to_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if message.get("content"):
        blocks.append({"type": "text", "text": message["content"]})
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            # Malformed arguments: drop the call, leave a note. The loop's
            # no-tool-use nudge (or the remaining parsed calls) lets the model
            # recover; an empty-input `done` would falsely fail the task.
            blocks.append({
                "type": "text",
                "text": f"[tool call {fn.get('name')} dropped: unparseable arguments]",
            })
            continue
        blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                       "name": fn.get("name", ""), "input": args})
    return blocks


class OpenAICompatClient:
    """LLMClient over the OpenAI Chat Completions API (httpx).

    ``base_url`` includes the version segment (e.g. ``https://api.openai.com/v1``);
    the client appends ``/chat/completions``. ``use_max_completion_tokens``
    selects the token-limit parameter name: native OpenAI requires
    ``max_completion_tokens``; OpenAI-compatible gateways expect ``max_tokens``.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        use_max_completion_tokens: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._use_max_completion_tokens = use_max_completion_tokens

    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        credential: str,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(system, messages),
        }
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"],
                              "parameters": t["input_schema"]}}
                for t in tools
            ]
        token_param = (
            "max_completion_tokens" if self._use_max_completion_tokens else "max_tokens"
        )
        payload[token_param] = max_tokens

        headers = {
            "authorization": f"Bearer {credential}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("error", {}).get("message", resp.text)
            except Exception:  # noqa: BLE001 — non-JSON error body
                message = resp.text
            raise RuntimeError(f"openai api error {resp.status_code}: {message}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason") or ""
        return LLMResponse(
            content=_to_blocks(choice.get("message") or {}),
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            stop_reason=_FINISH_TO_STOP.get(finish, finish),
        )
