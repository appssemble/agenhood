# services/control_plane/tests/test_api_driver_limits.py
"""api driver: driver-aware worker cap + catalog/allowed-driver membership."""
import pytest

from control_plane.tenant_defaults import (
    default_limits,
    merge_limits,
    worker_cap_for_driver,
)

pytestmark = pytest.mark.unit


def test_default_includes_api_worker_cap_and_driver():
    d = default_limits()
    assert d["api_driver_max_workers"] == 32
    assert "api" in d["allowed_drivers"]


def test_worker_cap_api_vs_others():
    limits = default_limits()
    assert worker_cap_for_driver(limits, "api") == 32
    assert worker_cap_for_driver(limits, "vanilla") == 4
    assert worker_cap_for_driver(limits, "opencode") == 4


def test_worker_cap_respects_tenant_overrides():
    limits = merge_limits({"api_driver_max_workers": 8,
                           "max_concurrent_tasks_per_container": 2})
    assert worker_cap_for_driver(limits, "api") == 8
    assert worker_cap_for_driver(limits, "vanilla") == 2


def test_existing_tenant_rows_inherit_new_key_at_read_time():
    # Stored rows predate the key; merge_limits layers them over current
    # defaults, so the new key must appear.
    stored = {"max_concurrent_tasks_per_container": 4, "max_containers": 10}
    assert merge_limits(stored)["api_driver_max_workers"] == 32


def test_model_catalog_offers_api_wherever_vanilla_is():
    from control_plane.model_catalog import _PROVIDER_DRIVERS

    for provider, drivers in _PROVIDER_DRIVERS.items():
        if "vanilla" in drivers:
            assert "api" in drivers, f"{provider} missing api"
        else:
            assert "api" not in drivers, f"{provider} should not offer api"
