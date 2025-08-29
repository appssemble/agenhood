"""Single-line JSON log builder, shape per spec §12: {ts, level, msg, ...}."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def log_line(*, level: str, msg: str, **extras: Any) -> str:
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "level": level,
        "msg": msg,
    }
    for k, v in extras.items():
        if v is not None:
            record[k] = v
    # ensure_ascii=False keeps unicode readable; the JSON string escaping
    # turns any embedded newline into \n so the line stays single-line.
    return json.dumps(record, ensure_ascii=False)
