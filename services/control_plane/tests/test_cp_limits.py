"""Task 13: Unit tests for tenant-backed limit resolution (control_plane.limits)."""
import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskLimits
from control_plane.limits import LimitExceeded, resolve_limits

TENANT = {
    "default_max_iterations": 30,
    "default_max_tokens": 2_000_000,
    "default_task_timeout_seconds": 1800,
}


def _cfg(**kw: object) -> AgentConfig:
    return AgentConfig(driver="vanilla", model="claude-opus-4-7", **kw)  # type: ignore[arg-type]


def test_defaults_applied_when_task_omits():
    r = resolve_limits(TaskLimits(), TENANT)
    assert r == ResolvedLimits(max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800)


def test_task_may_request_smaller():
    r = resolve_limits(TaskLimits(max_iterations=5, max_tokens=1000, timeout_seconds=60), TENANT)
    assert r == ResolvedLimits(max_iterations=5, max_tokens=1000, timeout_seconds=60)


def test_task_above_iteration_ceiling_rejected():
    with pytest.raises(LimitExceeded) as e:
        resolve_limits(TaskLimits(max_iterations=999), TENANT)
    assert e.value.field == "limits.max_iterations"


def test_task_above_token_ceiling_rejected():
    with pytest.raises(LimitExceeded) as e:
        resolve_limits(TaskLimits(max_tokens=9_000_000), TENANT)
    assert e.value.field == "limits.max_tokens"


def test_task_above_timeout_ceiling_rejected():
    with pytest.raises(LimitExceeded) as e:
        resolve_limits(TaskLimits(timeout_seconds=99999), TENANT)
    assert e.value.field == "limits.timeout_seconds"


# ---- per-container config overrides ----------------------------------------

def test_container_override_used_when_task_omits():
    cfg = _cfg(max_tokens=1000, timeout_seconds=120, max_iterations=7)
    r = resolve_limits(TaskLimits(), TENANT, cfg)
    assert r == ResolvedLimits(max_iterations=7, max_tokens=1000, timeout_seconds=120)


def test_task_request_overrides_container_default():
    cfg = _cfg(max_tokens=1000)
    r = resolve_limits(TaskLimits(max_tokens=500), TENANT, cfg)
    assert r.max_tokens == 500


def test_partial_container_override_falls_back_to_tenant_default():
    cfg = _cfg(max_tokens=1000)  # only max_tokens set
    r = resolve_limits(TaskLimits(), TENANT, cfg)
    assert r == ResolvedLimits(max_iterations=30, max_tokens=1000, timeout_seconds=1800)


def test_container_override_above_ceiling_is_clamped():
    # Defensive: a stored override above a (since-lowered) tenant ceiling is clamped.
    cfg = _cfg(max_tokens=9_000_000)
    r = resolve_limits(TaskLimits(), TENANT, cfg)
    assert r.max_tokens == TENANT["default_max_tokens"]


def test_task_above_ceiling_rejected_even_with_lower_container_override():
    cfg = _cfg(max_tokens=1000)
    with pytest.raises(LimitExceeded) as e:
        resolve_limits(TaskLimits(max_tokens=9_000_000), TENANT, cfg)
    assert e.value.field == "limits.max_tokens"
