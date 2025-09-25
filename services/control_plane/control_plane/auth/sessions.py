from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from control_plane.auth.tokens import generate_session_token, hash_token
from control_plane.ids_compat import new_id

# decision §14.7: 14-day sliding lifetime.
SESSION_TTL = timedelta(days=14)


def build_session_row(*, user_id: str, at: datetime | None = None) -> tuple[str, dict[str, Any]]:
    """Returns (plaintext_token, row). Caller persists the row and sets the
    cookie to plaintext_token. Only the hash is stored."""
    at = at or datetime.now(UTC)
    token = generate_session_token()
    row: dict[str, Any] = {
        "id": new_id("ses"),
        "user_id": user_id,
        "token_hash": hash_token(token),
        "created_at": at,
        "last_seen_at": at,
        "expires_at": at + SESSION_TTL,
        "revoked_at": None,
    }
    return token, row


def validate_and_slide(row: dict[str, Any], *, at: datetime | None = None) -> dict[str, Any] | None:
    """Returns the row with refreshed last_seen_at/expires_at if still valid,
    else None (expired or revoked). Pure: caller persists the returned diff."""
    at = at or datetime.now(UTC)
    if row.get("revoked_at") is not None:
        return None
    if row["expires_at"] <= at:
        return None
    updated = dict(row)
    updated["last_seen_at"] = at
    updated["expires_at"] = at + SESSION_TTL
    return updated
