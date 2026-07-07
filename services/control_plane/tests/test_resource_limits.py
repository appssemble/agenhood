from __future__ import annotations

import pytest

from control_plane.config import Settings
from control_plane.errors import APIError
from control_plane.resource_limits import resolve_resource_limits

pytestmark = pytest.mark.unit


def _settings(**over):
    base = dict(
        database_url="x", seed_tenant_id="t", seed_api_key="k", seed_llm_api_key="",
        agent_image_tag="dev", internal_network="agent-runtime-internal",
        readyz_timeout_seconds=1.0, shim_port=8080,
    )
    base.update(over)
    return Settings(**base)


def test_full_variant_default():
    mem, cpus = resolve_resource_limits(
        variant="full", requested_mem_limit=None, requested_cpus=None,
        settings=_settings(),
    )
    assert (mem, cpus) == ("4g", 2.0)


def test_slim_variant_default():
    mem, cpus = resolve_resource_limits(
        variant="slim", requested_mem_limit=None, requested_cpus=None,
        settings=_settings(),
    )
    assert (mem, cpus) == ("2g", 1.0)


def test_override_mem_only_keeps_variant_cpus():
    mem, cpus = resolve_resource_limits(
        variant="slim", requested_mem_limit="3g", requested_cpus=None,
        settings=_settings(),
    )
    assert (mem, cpus) == ("3g", 1.0)


def test_override_cpus_only_keeps_variant_mem():
    mem, cpus = resolve_resource_limits(
        variant="full", requested_mem_limit=None, requested_cpus=1.5,
        settings=_settings(),
    )
    assert (mem, cpus) == ("4g", 1.5)


def test_override_both():
    mem, cpus = resolve_resource_limits(
        variant="full", requested_mem_limit="6g", requested_cpus=3.0,
        settings=_settings(),
    )
    assert (mem, cpus) == ("6g", 3.0)


def test_mem_below_min_rejected():
    with pytest.raises(APIError) as ei:
        resolve_resource_limits(
            variant="full", requested_mem_limit="100m", requested_cpus=None,
            settings=_settings(),
        )
    assert ei.value.status_code == 400
    assert ei.value.code == "validation_error"
    assert ei.value.field == "resource_limits.mem_limit"


def test_mem_above_max_rejected():
    with pytest.raises(APIError) as ei:
        resolve_resource_limits(
            variant="full", requested_mem_limit="16g", requested_cpus=None,
            settings=_settings(),
        )
    assert ei.value.status_code == 400
    assert ei.value.field == "resource_limits.mem_limit"


def test_cpus_below_min_rejected():
    with pytest.raises(APIError) as ei:
        resolve_resource_limits(
            variant="full", requested_mem_limit=None, requested_cpus=0.1,
            settings=_settings(),
        )
    assert ei.value.status_code == 400
    assert ei.value.field == "resource_limits.cpus"


def test_cpus_above_max_rejected():
    with pytest.raises(APIError) as ei:
        resolve_resource_limits(
            variant="full", requested_mem_limit=None, requested_cpus=10.0,
            settings=_settings(),
        )
    assert ei.value.status_code == 400
    assert ei.value.field == "resource_limits.cpus"


def test_malformed_mem_string_rejected():
    with pytest.raises(APIError) as ei:
        resolve_resource_limits(
            variant="full", requested_mem_limit="lots", requested_cpus=None,
            settings=_settings(),
        )
    assert ei.value.status_code == 400
    assert ei.value.field == "resource_limits.mem_limit"


def test_bounds_are_inclusive():
    mem, cpus = resolve_resource_limits(
        variant="full", requested_mem_limit="256m", requested_cpus=4.0,
        settings=_settings(),
    )
    assert (mem, cpus) == ("256m", 4.0)
