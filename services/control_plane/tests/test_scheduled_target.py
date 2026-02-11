import pytest

from control_plane.errors import APIError
from control_plane.scheduled_target import validate_target

pytestmark = pytest.mark.unit


def test_prompt_target_ok():
    t = validate_target(
        {
            "kind": "prompt",
            "container_id": "con_1",
            "prompt_id": "prm_1",
            "variables": {"a": 1},
        }
    )
    assert t["kind"] == "prompt" and t["variables"] == {"a": "1"}


def test_workflow_target_ok():
    assert validate_target({"kind": "workflow", "workflow_id": "wf_1"})["workflow_id"] == "wf_1"


def test_bad_kind_rejected():
    with pytest.raises(APIError) as ei:
        validate_target({"kind": "nope"})
    assert getattr(ei.value, "field", None) == "target"


def test_prompt_target_missing_fields_rejected():
    with pytest.raises(APIError):
        validate_target({"kind": "prompt", "prompt_id": "prm_1"})  # no container_id
