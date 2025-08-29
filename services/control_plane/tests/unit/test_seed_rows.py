import pytest

from agentcore.drivers.base import DRIVERS
from control_plane.seed import SEED_TENANT_LIMITS, build_builtin_template_rows

pytestmark = pytest.mark.unit


def test_one_builtin_row_per_driver():
    rows = build_builtin_template_rows()
    assert len(rows) == len(DRIVERS)
    by_driver = {r["driver"]: r for r in rows}
    assert set(by_driver) == set(DRIVERS)


def test_builtin_row_copies_driver_template():
    rows = build_builtin_template_rows()
    for r in rows:
        dt = DRIVERS[r["driver"]].default_template
        assert r["is_builtin"] is True
        assert r["tenant_id"] is None
        assert r["system_prompt"] == dt.default_system_prompt
        assert r["tools"] == dt.available_tools
        assert r["system_prompt_mode"] == "augment"
        assert r["id"].startswith("tpl_")


def test_seed_tenant_limits_do_not_freeze_drivers():
    # allowed_drivers is resolved from current defaults at read time, never frozen
    # into the seed snapshot (so a newly added driver reaches the seed tenant).
    assert "allowed_drivers" not in SEED_TENANT_LIMITS
    assert "allowed_models" not in SEED_TENANT_LIMITS
    assert SEED_TENANT_LIMITS["max_concurrent_tasks_per_container"] >= 1
