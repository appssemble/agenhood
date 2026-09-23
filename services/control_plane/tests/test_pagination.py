from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane.errors import APIError
from control_plane.pagination import clamp_limit, decode_cursor, encode_cursor

pytestmark = pytest.mark.unit


def test_cursor_round_trips_with_microseconds() -> None:
    ts = datetime(2026, 9, 23, 10, 11, 12, 345678, tzinfo=UTC)
    assert decode_cursor(encode_cursor(ts, "tsk_abc")) == (ts, "tsk_abc")


@pytest.mark.parametrize(
    "bad",
    [
        "not base64 !!",
        "e30",  # {}
        "eyJ0cyI6IjIwMjYtMDEtMDFUMDA6MDA6MDAiLCJrZXkiOiJ4In0",  # naive timestamp
        "eyJ0cyI6Im5vcGUiLCJrZXkiOiJ4In0",  # unparsable timestamp
        "eyJ0cyI6IjIwMjYtMDEtMDFUMDA6MDA6MDArMDA6MDAiLCJrZXkiOjF9",  # non-string key
        "WzFd",  # [1]
    ],
)
def test_malformed_cursor_is_400(bad: str) -> None:
    with pytest.raises(APIError) as exc:
        decode_cursor(bad)
    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_cursor"


@pytest.mark.parametrize(("given", "expected"), [(0, 1), (-5, 1), (50, 50), (999, 200)])
def test_clamp_limit(given: int, expected: int) -> None:
    assert clamp_limit(given, 200) == expected
