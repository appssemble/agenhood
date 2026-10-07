"""Translate ``codex app-server`` notifications into ``codex exec --json`` events.

The console and API clients read codex events in the exec shape, so the driver
keeps emitting that shape although turns run on the app-server.
"""

from __future__ import annotations

import re
from typing import Any

_USAGE_KEYS = (
    ("input_tokens", "inputTokens"),
    ("cached_input_tokens", "cachedInputTokens"),
    ("cache_write_input_tokens", "cacheWriteInputTokens"),
    ("output_tokens", "outputTokens"),
    ("reasoning_output_tokens", "reasoningOutputTokens"),
)


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()


def _web_action(action: dict[str, Any] | None) -> dict[str, Any]:
    if not action:
        return {"type": "other"}
    out = {key: value for key, value in action.items() if value is not None}
    out["type"] = _snake(str(action.get("type", "other")))
    return out


def _change_kind(kind: Any) -> Any:
    return kind.get("type") if isinstance(kind, dict) else kind


class ExecEventTranslator:
    """Per turn: numbers items like exec (``item_N``) and sums token usage."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._usage = {key: 0 for key, _ in _USAGE_KEYS}

    def thread_started(self, thread_id: str) -> dict[str, Any]:
        return {"type": "thread.started", "thread_id": thread_id}

    def translate(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "turn/started":
            return [{"type": "turn.started"}]
        if method in ("item/started", "item/completed"):
            completed = method == "item/completed"
            item = self._item(params.get("item") or {}, completed=completed)
            if item is None:
                return []
            return [{"type": "item.completed" if completed else "item.started", "item": item}]
        if method == "warning":
            item = {"id": self._id(None), "type": "error", "message": params.get("message", "")}
            return [{"type": "item.completed", "item": item}]
        if method == "thread/tokenUsage/updated":
            last = (params.get("tokenUsage") or {}).get("last") or {}
            for key, source in _USAGE_KEYS:
                self._usage[key] += int(last.get(source) or 0)
            return []
        if method == "error":
            return [{"type": "error", "message": (params.get("error") or {}).get("message", "")}]
        if method == "turn/completed":
            turn = params.get("turn") or {}
            if turn.get("status") == "completed":
                return [{"type": "turn.completed", "usage": dict(self._usage)}]
            if turn.get("status") == "failed":
                text = (turn.get("error") or {}).get("message") or "turn failed"
                return [{"type": "turn.failed", "error": {"message": text}}]
        return []

    def _id(self, source_id: str | None, *, keep: bool = False) -> str:
        if source_id is not None and source_id in self._ids:
            return self._ids[source_id]
        new_id = source_id if keep and source_id else f"item_{len(self._ids)}"
        self._ids[source_id if source_id is not None else new_id] = new_id
        return new_id

    def _item(self, item: dict[str, Any], *, completed: bool) -> dict[str, Any] | None:
        kind = item.get("type")
        source_id = item.get("id")
        status = _snake(str(item.get("status") or "completed"))
        if kind == "agentMessage":
            if not completed:
                return None
            return {"id": self._id(source_id), "type": "agent_message",
                    "text": item.get("text", "")}
        if kind == "reasoning":
            summary = [part for part in item.get("summary") or [] if part]
            if not completed or not summary:
                return None
            return {"id": self._id(source_id), "type": "reasoning", "text": "\n\n".join(summary)}
        if kind == "commandExecution":
            return {
                "id": self._id(source_id),
                "type": "command_execution",
                "command": item.get("command", ""),
                "aggregated_output": item.get("aggregatedOutput") or "",
                "exit_code": item.get("exitCode"),
                "status": status,
            }
        if kind == "fileChange":
            changes = [
                {"path": change.get("path"), "kind": _change_kind(change.get("kind"))}
                for change in item.get("changes") or []
            ]
            return {"id": self._id(source_id), "type": "file_change", "changes": changes,
                    "status": status}
        if kind == "webSearch":
            out = {
                "id": self._id(source_id, keep=True),
                "type": "web_search",
                "query": item.get("query", ""),
                "action": _web_action(item.get("action")),
            }
            if completed and item.get("results") is not None:
                out["results"] = item["results"]
            return out
        if kind == "mcpToolCall":
            return {
                "id": self._id(source_id),
                "type": "mcp_tool_call",
                "server": item.get("server", ""),
                "tool": item.get("tool", ""),
                "arguments": item.get("arguments"),
                "result": item.get("result"),
                "error": item.get("error"),
                "status": status,
            }
        return None
