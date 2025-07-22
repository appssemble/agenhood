from __future__ import annotations

import json
from typing import Any


def classify_json_line(line: str) -> tuple[str, object | None]:
    """Classify one line from a JSONL-capable CLI driver stream."""
    stripped = line.strip()
    if not stripped:
        return "ignore", None
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return "event", json.loads(stripped)
        except json.JSONDecodeError:
            return "stdout", stripped
    return "stdout", stripped


def log_payload(
    op: str,
    *,
    level: str = "info",
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a log payload with the normalized shape plus old top-level fields."""
    payload_data = dict(data or {})
    return {
        "op": op,
        "level": level,
        "message": message or op,
        "data": payload_data,
        **payload_data,
    }
