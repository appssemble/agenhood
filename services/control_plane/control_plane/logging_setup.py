"""Structured JSON logging for the control plane (spec §12).

Shape: {ts, level, msg, tenant_id?, container_id?, task_id?, ...extras}.
Optional context fields are emitted via `logger.info(msg, extra={...})`.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Fields we promote from the LogRecord into the JSON line when present.
_CONTEXT_FIELDS = ("tenant_id", "container_id", "task_id")

# Standard LogRecord attributes we never want to copy as "extras".
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                out[field] = value
        # Any other non-reserved attribute set via extra= becomes a top-level key.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in _CONTEXT_FIELDS or key == "msg":
                continue
            if not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger's stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
