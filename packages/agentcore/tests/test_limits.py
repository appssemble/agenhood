import pytest

from agentcore.errors import ValidationError
from agentcore.limits import LimitExceededError, resolve_limits
from agentcore.models import ResolvedLimits, TaskLimits

DEFAULTS = ResolvedLimits(max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800)
CEILINGS = ResolvedLimits(max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800)


def test_omitted_fields_take_the_defaults():
    resolved = resolve_limits(TaskLimits(), DEFAULTS, CEILINGS)
    assert resolved == ResolvedLimits(
        max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800
    )


def test_smaller_request_is_honored_per_field():
    resolved = resolve_limits(
        TaskLimits(max_iterations=10, max_tokens=500_000, timeout_seconds=600),
        DEFAULTS,
        CEILINGS,
    )
    assert resolved == ResolvedLimits(
        max_iterations=10, max_tokens=500_000, timeout_seconds=600
    )


def test_partial_request_mixes_request_and_default():
    # Only max_iterations supplied; the other two fall back to defaults.
    resolved = resolve_limits(TaskLimits(max_iterations=5), DEFAULTS, CEILINGS)
    assert resolved == ResolvedLimits(
        max_iterations=5, max_tokens=2_000_000, timeout_seconds=1800
    )


def test_above_ceiling_raises_validation_error_with_field_and_code():
    with pytest.raises(LimitExceededError) as exc:
        resolve_limits(TaskLimits(max_tokens=9_000_000), DEFAULTS, CEILINGS)
    # LimitExceededError is a ValidationError (code "validation_error", §6.2).
    assert isinstance(exc.value, ValidationError)
    assert exc.value.code == "validation_error"
    assert exc.value.field == "limits.max_tokens"


def test_above_ceiling_checks_each_field_independently():
    with pytest.raises(LimitExceededError) as exc:
        resolve_limits(TaskLimits(timeout_seconds=3600), DEFAULTS, CEILINGS)
    assert exc.value.field == "limits.timeout_seconds"
    with pytest.raises(LimitExceededError) as exc2:
        resolve_limits(TaskLimits(max_iterations=31), DEFAULTS, CEILINGS)
    assert exc2.value.field == "limits.max_iterations"
