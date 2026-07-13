"""validate_config: effort allowed only for the CLI drivers."""
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig
from control_plane.config_validation import EFFORT_DRIVERS, validate_config
from control_plane.errors import APIError

# Adapt tenant_limits construction to match tests/test_config_validation_limits.py.
LIMITS = {"allowed_drivers": ["vanilla", "opencode", "claude-code", "codex"]}


def test_effort_drivers_is_the_cli_trio():
    assert EFFORT_DRIVERS == {"opencode", "claude-code", "codex"}


def test_effort_accepted_for_codex():
    cfg = AgentConfig(driver="codex", model="gpt-5.4", effort="high")
    validate_config(cfg, LIMITS)  # must not raise


def test_effort_rejected_for_vanilla():
    cfg = AgentConfig(driver="vanilla", model="claude-opus-4-7", effort="high")
    with pytest.raises(APIError) as exc:
        validate_config(cfg, LIMITS)
    assert exc.value.field == "effort"
