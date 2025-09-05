from __future__ import annotations

import json
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


def should_forward(*, seq: int, after_seq: int | None) -> bool:
    """Forward an event only if it is strictly after `after_seq` (or no filter)."""
    if after_seq is None:
        return True
    return seq > after_seq
