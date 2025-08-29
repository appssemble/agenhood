import pytest

from agentcore.models import ResolvedLimits, TaskLimits
from control_plane.errors import APIError
from control_plane.limits_resolve import resolve_task_limits

pytestmark = pytest.mark.unit

TENANT_LIMITS = {
    "default_max_iterations": 30,
    "default_max_tokens": 2_000_000,
    "default_task_timeout_seconds": 1800,
}


def test_unset_limits_take_tenant_defaults():
    out = resolve_task_limits(TaskLimits(), TENANT_LIMITS)
    assert out == ResolvedLimits(
        max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800
    )


def test_smaller_request_is_honored():
    out = resolve_task_limits(
        TaskLimits(max_iterations=5, max_tokens=1000, timeout_seconds=60), TENANT_LIMITS
    )
    assert out == ResolvedLimits(max_iterations=5, max_tokens=1000, timeout_seconds=60)


def test_request_above_ceiling_is_rejected():
    with pytest.raises(APIError) as ei:
        resolve_task_limits(TaskLimits(max_iterations=999), TENANT_LIMITS)
    assert ei.value.code == "validation_error"
    assert ei.value.field == "max_iterations"
