from __future__ import annotations

from control_plane.auth.ratelimit import FixedWindowLimiter


def test_allows_up_to_limit_then_blocks():
    lim = FixedWindowLimiter(max_attempts=3, window_seconds=60)
    key = "owner@example.com|1.2.3.4"
    assert lim.allow(key, now=0.0) is True   # 1
    assert lim.allow(key, now=1.0) is True   # 2
    assert lim.allow(key, now=2.0) is True   # 3
    assert lim.allow(key, now=3.0) is False  # blocked


def test_window_resets():
    lim = FixedWindowLimiter(max_attempts=2, window_seconds=60)
    key = "a|b"
    assert lim.allow(key, now=0.0) is True
    assert lim.allow(key, now=0.5) is True
    assert lim.allow(key, now=1.0) is False
    assert lim.allow(key, now=61.0) is True  # new window
