from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def format_sse(data: str) -> str:
    """Wrap a JSON string as one SSE `data:` frame."""
    return f"data: {data}\n\n"


def parse_event_line(line: str) -> dict[str, Any] | None:
    """Parse a single SSE line into an event dict, or None for non-data lines."""
    if not line.startswith("data:"):
        return None
    raw = line[len("data:"):].strip()
    if not raw:
        return None
    try:
        result: dict[str, Any] = json.loads(raw)
        return result
    except json.JSONDecodeError:
        return None


def event_ts(event: dict[str, Any]) -> datetime:
    """The shim's own timestamp for an event, falling back to now().

    The shim stamps each event as it appends to the task's log; preserving
    that value is what keeps a replayed backlog from collapsing every stored
    duration to zero. Persistence is best-effort, so a missing or malformed
    value must never cost us the event.
    """
    raw = event.get("ts")
    if not isinstance(raw, str):
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def should_forward(*, seq: int, after_seq: int | None) -> bool:
    """Forward an event only if it is strictly after `after_seq` (or no filter)."""
    if after_seq is None:
        return True
    return seq > after_seq
