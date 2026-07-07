from __future__ import annotations

import pytest

from control_plane.schemas import ContainerOut, CreateContainerRequest, ResourceLimitsIn

pytestmark = pytest.mark.unit


def test_create_request_resource_limits_optional():
    req = CreateContainerRequest(name="x")
    assert req.resource_limits is None


def test_create_request_resource_limits_partial():
    req = CreateContainerRequest(name="x", resource_limits={"cpus": 1.5})
    assert req.resource_limits == ResourceLimitsIn(mem_limit=None, cpus=1.5)


def test_container_out_requires_mem_limit_and_cpus():
    out = ContainerOut(
        id="con_1", name="x", external_id=None, metadata={}, status="running",
        image_tag="dev", image_variant="full", template_id=None,
        config={"driver": "vanilla", "model": "m", "system_prompt": "",
                "system_prompt_mode": "augment", "tools": [], "context": {}},
        last_task_at=None, created_at="2026-07-07T00:00:00Z", error_message=None,
        mem_limit="4g", cpus=2.0,
    )
    assert out.mem_limit == "4g"
    assert out.cpus == 2.0
