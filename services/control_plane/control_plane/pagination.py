"""Opaque keyset cursors for paginated list endpoints."""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from control_plane.errors import api_error


def encode_cursor(ts: datetime, key: str) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "key": key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Return the (timestamp, tie-break key) a cursor points after; 400 if malformed."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        ts = datetime.fromisoformat(data["ts"])
        key = data["key"]
    except (binascii.Error, ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise api_error(400, "invalid_cursor", "cursor is malformed", field="cursor") from None
    if ts.tzinfo is None or not isinstance(key, str):
        raise api_error(400, "invalid_cursor", "cursor is malformed", field="cursor")
    return ts, key


def clamp_limit(limit: int, maximum: int) -> int:
    return max(1, min(limit, maximum))
