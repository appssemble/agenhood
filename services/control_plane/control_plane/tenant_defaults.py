from __future__ import annotations

from copy import deepcopy

# spec §4.4 — the canonical per-tenant limits block.
_DEFAULTS: dict = {  # type: ignore[type-arg]
    "max_containers": 2000,
    "max_running_containers": 30,
    "max_users": 25,
    "max_concurrent_tasks_per_container": 4,
    # Worker cap for containers running the `api` driver (single-call, no
    # tools/subprocesses — safe at much higher concurrency than the default).
    "api_driver_max_workers": 32,
    "max_workspace_volume_size_mb": 10240,
    "default_task_timeout_seconds": 1800,
    "default_max_iterations": 30,
    "default_max_tokens": 2000000,
    "idle_pause_minutes": 20,
    "archive_after_hours": 72,
    "reclaim_after_days": 30,
    "allowed_drivers": ["vanilla", "opencode", "codex", "claude-code", "api"],
}


def default_limits() -> dict:  # type: ignore[type-arg]
    return deepcopy(_DEFAULTS)


def merge_limits(overrides: dict | None) -> dict:  # type: ignore[type-arg]
    """Resolve a tenant's *effective* limits: current defaults with any stored
    overrides layered on top. This is the read-time resolver — call it wherever
    effective limits are needed (validation, ``/me``) so that a tenant which did
    not freeze a key inherits the current default for it.
    """
    merged = default_limits()
    if overrides:
        merged.update(overrides)
    return merged


def persisted_limits(overrides: dict | None) -> dict:  # type: ignore[type-arg]
    """The limits dict to *store* for a tenant at creation.

    We materialize the numeric defaults so the row is self-describing, but we
    deliberately do NOT freeze ``allowed_drivers``: driver availability tracks the
    platform's installed driver set, which grows across releases. Leaving the key
    unset means ``merge_limits`` supplies the *current* default set at read time,
    so adding a driver to ``_DEFAULTS`` grants it to every non-restricted tenant
    with no backfill. An admin restricts a tenant by passing an explicit
    ``allowed_drivers`` in ``overrides`` — that IS persisted and wins on merge.
    """
    stored = merge_limits(overrides)
    if not (overrides and "allowed_drivers" in overrides):
        stored.pop("allowed_drivers", None)
    return stored


def worker_cap_for_driver(limits: dict, driver: str) -> int:  # type: ignore[type-arg]
    """Per-container concurrent-task cap, driver-aware.

    The api driver runs single-call tasks with no subprocesses or workspace
    writes, so it gets its own (much higher) default cap.
    """
    if driver == "api":
        return int(limits.get("api_driver_max_workers", 32))
    return int(limits.get("max_concurrent_tasks_per_container", 4))
