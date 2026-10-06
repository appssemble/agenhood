"""validate_config: reasoning_summary allowed only for drivers that support it."""
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig
from control_plane.config_validation import REASONING_SUMMARY_DRIVERS, validate_config
from control_plane.errors import APIError

LIMITS = {"allowed_drivers": ["vanilla", "opencode", "claude-code", "codex"]}


def test_reasoning_summary_drivers_is_codex_only():
    assert REASONING_SUMMARY_DRIVERS == {"codex"}


def test_reasoning_summary_accepted_for_codex():
    cfg = AgentConfig(driver="codex", model="gpt-5.5", reasoning_summary=True)
    validate_config(cfg, LIMITS)


def test_reasoning_summary_rejected_for_vanilla():
    cfg = AgentConfig(driver="vanilla", model="claude-opus-4-7", reasoning_summary=True)
    with pytest.raises(APIError) as exc:
        validate_config(cfg, LIMITS)
    assert exc.value.field == "reasoning_summary"


def test_reasoning_summary_off_accepted_for_any_driver():
    cfg = AgentConfig(driver="vanilla", model="claude-opus-4-7", reasoning_summary=False)
    validate_config(cfg, LIMITS)
