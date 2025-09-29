from datetime import UTC, datetime, timedelta

import pytest

from control_plane.auth.sessions import (
    SESSION_TTL,
    build_session_row,
    validate_and_slide,
)
from control_plane.auth.tokens import hash_token

pytestmark = pytest.mark.unit


def now():
    return datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_build_session_row_stores_only_hash():
    token, row = build_session_row(user_id="usr_1", at=now())
    assert row["token_hash"] == hash_token(token)
    assert token not in row.values()                 # plaintext never stored
    assert row["expires_at"] == now() + SESSION_TTL
    assert row["revoked_at"] is None


def test_validate_and_slide_extends_expiry():
    _, row = build_session_row(user_id="usr_1", at=now() - timedelta(days=3))
    later = now()
    updated = validate_and_slide(row, at=later)
    assert updated is not None
    assert updated["expires_at"] == later + SESSION_TTL
    assert updated["last_seen_at"] == later


def test_validate_and_slide_rejects_expired():
    _, row = build_session_row(user_id="usr_1", at=now() - timedelta(days=20))
    assert validate_and_slide(row, at=now()) is None


def test_validate_and_slide_rejects_revoked():
    _, row = build_session_row(user_id="usr_1", at=now())
    row["revoked_at"] = now()
    assert validate_and_slide(row, at=now() + timedelta(hours=1)) is None
