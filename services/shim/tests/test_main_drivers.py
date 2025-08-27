import pytest

pytestmark = pytest.mark.unit


def test_build_drivers_includes_all_launch_drivers() -> None:
    """The shim builds its driver registry explicitly; every shipped driver
    must be present here or the shim rejects tasks for it (unknown driver)."""
    from shim.main import build_drivers

    drivers = build_drivers()
    assert set(drivers) == {"vanilla", "opencode", "codex", "claude-code"}
    assert drivers["codex"].name == "codex"
    assert drivers["claude-code"].name == "claude-code"
