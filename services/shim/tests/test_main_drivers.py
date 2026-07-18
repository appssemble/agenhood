import pytest

pytestmark = pytest.mark.unit


def test_build_drivers_includes_all_launch_drivers() -> None:
    """The shim builds its driver registry explicitly; every shipped driver
    must be present here or the shim rejects tasks for it (unknown driver)."""
    from shim.main import build_drivers

    drivers = build_drivers()
    assert set(drivers) == {"vanilla", "opencode", "codex", "claude-code", "api"}
    assert drivers["codex"].name == "codex"
    assert drivers["claude-code"].name == "claude-code"


def test_build_drivers_includes_api():
    from shim.main import build_drivers

    drivers = build_drivers()
    assert "api" in drivers
    assert drivers["api"].name == "api"


def test_build_drivers_vanilla_router_honors_env(monkeypatch) -> None:
    """OPENAI_BASE_URL / OPENCODE_GO_BASE_URL / ANTHROPIC_BASE_URL reach the
    vanilla driver's router clients (stub/test override mechanism)."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://stub:1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://stub:2/v1")
    monkeypatch.setenv("OPENCODE_GO_BASE_URL", "http://stub:3")

    from shim.main import build_drivers

    vanilla = build_drivers()["vanilla"]
    assert vanilla._router.route("claude-x")[0]._base_url == "http://stub:1"
    assert vanilla._router.route("gpt-x")[0]._base_url == "http://stub:2/v1"
    assert vanilla._router.route("opencode-go/qwen3.7-max")[0]._base_url == "http://stub:3"
    assert vanilla._router.route("opencode-go/glm-5.2")[0]._base_url == "http://stub:3/v1"
