from __future__ import annotations

from control_plane.tenant_defaults import default_limits, merge_limits, persisted_limits


def test_default_limits_match_spec() -> None:
    d = default_limits()
    assert d["max_containers"] == 2000
    assert d["max_running_containers"] == 30
    assert d["max_concurrent_tasks_per_container"] == 4
    assert d["default_task_timeout_seconds"] == 1800
    assert d["default_max_iterations"] == 30
    assert d["default_max_tokens"] == 2000000
    assert d["allowed_drivers"] == ["vanilla", "opencode", "codex", "claude-code"]


def test_merge_limits_overrides_only_supplied_keys() -> None:
    merged = merge_limits({"max_running_containers": 10})
    assert merged["max_running_containers"] == 10
    assert merged["max_containers"] == 2000  # untouched default


def test_defaults_have_no_allowed_models() -> None:
    from control_plane.tenant_defaults import default_limits
    lim = default_limits()
    assert "allowed_models" not in lim
    assert lim["allowed_drivers"] == ["vanilla", "opencode", "codex", "claude-code"]


def test_claude_code_in_default_allowed_drivers() -> None:
    d = default_limits()
    assert "claude-code" in d["allowed_drivers"]


def test_persisted_limits_does_not_freeze_allowed_drivers() -> None:
    # With no explicit override, allowed_drivers is left unset in storage so the
    # tenant inherits the current default set at read time (durability).
    stored = persisted_limits(None)
    assert "allowed_drivers" not in stored
    assert stored["max_containers"] == 2000  # numeric defaults still materialized
    # Resolving the stored row yields the current full driver set.
    assert merge_limits(stored)["allowed_drivers"] == [
        "vanilla", "opencode", "codex", "claude-code"
    ]


def test_persisted_limits_keeps_explicit_driver_restriction() -> None:
    # An admin-supplied allowed_drivers IS persisted and survives the merge — this
    # is how a tenant is deliberately restricted to a subset.
    stored = persisted_limits({"allowed_drivers": ["vanilla"]})
    assert stored["allowed_drivers"] == ["vanilla"]
    assert merge_limits(stored)["allowed_drivers"] == ["vanilla"]


def test_persisted_limits_inherits_future_driver_additions() -> None:
    # Simulate a tenant created before a new driver existed: a non-restricted row
    # has no allowed_drivers, so merge supplies whatever defaults currently list.
    stored = persisted_limits({"max_running_containers": 5})
    assert "allowed_drivers" not in stored
    assert "claude-code" in merge_limits(stored)["allowed_drivers"]
