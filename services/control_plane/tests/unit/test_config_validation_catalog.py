from __future__ import annotations

import pytest

from agentcore.models import AgentConfig
from control_plane import config_validation as cv
from control_plane.model_catalog import ModelEntry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    cat = [
        ModelEntry("claude-opus-4-8", "anthropic", "claude-opus-4-8", "api_key",
                   ("anthropic_api_key",), ("opencode", "vanilla")),
        ModelEntry("gpt-5.4", "openai", "gpt-5.4", "api_key",
                   ("openai_api_key",), ("opencode",)),
    ]
    monkeypatch.setattr(cv, "_catalog", lambda: cat)


_LIMITS = {"allowed_drivers": ["vanilla", "opencode"]}


def test_known_model_compatible_driver_passes() -> None:
    cv.validate_config(
        AgentConfig(driver="opencode", model="gpt-5.4", tools=[]), _LIMITS
    )  # no raise


def test_model_not_supported_by_driver_rejected() -> None:
    with pytest.raises(cv.APIErrorLike):
        cv.validate_config(
            AgentConfig(driver="vanilla", model="gpt-5.4", tools=[]), _LIMITS
        )


def test_unknown_model_rejected() -> None:
    with pytest.raises(cv.APIErrorLike):
        cv.validate_config(
            AgentConfig(driver="opencode", model="not-a-real-model", tools=[]), _LIMITS
        )


# ---- per-container limit overrides -----------------------------------------

_LIMITS_CEIL = {
    "allowed_drivers": ["vanilla", "opencode"],
    "default_max_iterations": 30,
    "default_max_tokens": 2_000_000,
    "default_task_timeout_seconds": 1800,
}


def test_container_limit_within_ceiling_passes() -> None:
    cv.validate_config(
        AgentConfig(driver="vanilla", model="claude-opus-4-8", tools=[],
                    max_iterations=10, max_tokens=1000, timeout_seconds=120),
        _LIMITS_CEIL,
    )  # no raise


def test_container_limit_above_ceiling_rejected() -> None:
    with pytest.raises(cv.APIErrorLike):
        cv.validate_config(
            AgentConfig(driver="vanilla", model="claude-opus-4-8", tools=[],
                        max_tokens=9_000_000),
            _LIMITS_CEIL,
        )


def test_container_limit_non_positive_rejected() -> None:
    with pytest.raises(cv.APIErrorLike):
        cv.validate_config(
            AgentConfig(driver="vanilla", model="claude-opus-4-8", tools=[],
                        timeout_seconds=0),
            _LIMITS_CEIL,
        )
