import pytest

pytestmark = pytest.mark.unit


def test_session_driver_mismatch_is_409():
    from control_plane.errors import session_driver_mismatch

    err = session_driver_mismatch("session sess-1 was created with driver codex")
    assert err.status_code == 409
    assert err.code == "session_driver_mismatch"


def test_session_busy_is_409():
    from control_plane.errors import session_busy

    err = session_busy("session sess-1 already has a task in flight")
    assert err.status_code == 409
    assert err.code == "session_busy"


def test_session_busy_default_message():
    from control_plane.errors import session_busy

    err = session_busy()
    assert err.status_code == 409
    assert err.code == "session_busy"
    assert err.message
