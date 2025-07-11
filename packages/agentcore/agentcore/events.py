"""Event type set + payload builders (spec §7).

Builders return only the ``payload`` dict for an event. The emitter assigns
``seq`` (monotonic per task) and ``ts`` and wraps these in an :class:`Event`.
"""

from __future__ import annotations

import typing
from typing import Any, Literal

from agentcore.models import EventType

# Frozen set form of the EventType literal, for membership checks/validation.
EVENT_TYPES: frozenset[str] = frozenset(typing.get_args(EventType))

LogLevel = Literal["info", "warn", "error"]
FileOperation = Literal["create", "modify", "delete"]


def task_started(driver: str, model: str) -> dict[str, Any]:
    return {"driver": driver, "model": model}


def iteration_started(iteration: int) -> dict[str, Any]:
    return {"iteration": iteration}


def assistant_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"content": content}


def tool_call(tool_use_id: str, name: str, input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_use_id": tool_use_id, "name": name, "input": input}


def tool_result(
    tool_use_id: str, *, ok: bool, content: str, duration_ms: int
) -> dict[str, Any]:
    return {
        "tool_use_id": tool_use_id,
        "ok": ok,
        "content": content,
        "duration_ms": duration_ms,
    }


def token_update(*, tokens_in: int, tokens_out: int) -> dict[str, Any]:
    return {"tokens_in": tokens_in, "tokens_out": tokens_out}


def file_changed(path: str, operation: FileOperation, size: int) -> dict[str, Any]:
    return {"path": path, "operation": operation, "size": size}


def opencode_stdout(line: str) -> dict[str, Any]:
    return {"line": line}


def opencode_event(raw: dict[str, Any]) -> dict[str, Any]:
    return {"raw": raw}


def codex_stdout(line: str) -> dict[str, Any]:
    return {"line": line}


def codex_event(raw: dict[str, Any]) -> dict[str, Any]:
    return {"raw": raw}


def claude_stdout(line: str) -> dict[str, Any]:
    return {"line": line}


def claude_event(raw: dict[str, Any]) -> dict[str, Any]:
    return {"raw": raw}


def status_change(
    *,
    from_status: str,
    to_status: str,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    return {"from": from_status, "to": to_status, "result": result, "error": error}


def log(
    level: LogLevel, message: str, *, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"level": level, "message": message, "data": data or {}}
