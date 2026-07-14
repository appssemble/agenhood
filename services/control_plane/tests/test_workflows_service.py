import pytest

from control_plane.errors import APIError
from control_plane.workflows_service import (
    build_workflow_row,
    run_view,
    validate_workflow_fields,
    workflow_view,
)

pytestmark = pytest.mark.unit


def test_validate_rejects_empty_steps():
    with pytest.raises(APIError) as ei:
        validate_workflow_fields(name="W", description=None, steps=[])
    assert getattr(ei.value, "field", None) == "steps"


def test_validate_rejects_step_missing_prompt_or_container():
    with pytest.raises(APIError):
        validate_workflow_fields(name="W", description=None, steps=[{"container_id": "con_1"}])
    with pytest.raises(APIError):
        validate_workflow_fields(name="W", description=None, steps=[{"prompt_id": "prm_1"}])


def test_validate_normalizes_variables_to_string_map():
    steps = validate_workflow_fields(
        name="W", description=None,
        steps=[{"prompt_id": "prm_1", "container_id": "con_1", "variables": {"x": 7}}],
    )
    assert steps == [
        {"prompt_id": "prm_1", "container_id": "con_1", "variables": {"x": "7"}, "exports": []}
    ]


def test_build_and_view_roundtrip_hides_tenant():
    row = build_workflow_row(
        tenant_id="ten_1", created_by="usr_1", name=" W ", description="d",
        steps=[{"prompt_id": "prm_1", "container_id": "con_1", "variables": {}}],
    )
    assert row["id"].startswith("wf_")
    assert row["name"] == "W"
    v = workflow_view(row)
    assert "tenant_id" not in v
    assert v["steps"][0]["prompt_id"] == "prm_1"


def test_run_view_shape():
    v = run_view({
        "id": "wfr_1", "workflow_id": "wf_1", "status": "running", "cursor": 0,
        "current_task_id": "tsk_1", "step_count": 2, "error_step": None,
        "error_message": None, "trigger_source": "api", "scheduled_task_id": None,
        "started_at": "2026-06-28T00:00:00+00:00", "ended_at": None,
    })
    assert v["status"] == "running" and v["step_count"] == 2 and "tenant_id" not in v


# ---- step exports (workflow file transfer) -----------------------------------

def _steps_with_exports(exports):
    return [{"prompt_id": "prm_1", "container_id": "con_1", "exports": exports}]


def test_step_exports_normalized_and_stripped():
    out = validate_workflow_fields(
        name="wf", description=None,
        steps=_steps_with_exports([" report.pdf ", "dist/**"]),
    )
    assert out[0]["exports"] == ["report.pdf", "dist/**"]


def test_step_without_exports_gets_empty_list():
    out = validate_workflow_fields(
        name="wf", description=None,
        steps=[{"prompt_id": "prm_1", "container_id": "con_1"}],
    )
    assert out[0]["exports"] == []


@pytest.mark.parametrize("bad", [
    "not-a-list",
    ["/abs/path.txt"],
    ["a/../b.txt"],
    [".git/config"],
    [".agent-runtime/x"],
    [".agent-state/x"],
    [""],
    ["  "],
    [123],
    ["x" * 513],
])
def test_step_exports_invalid_rejected(bad):
    with pytest.raises(APIError) as ei:
        validate_workflow_fields(
            name="wf", description=None, steps=_steps_with_exports(bad),
        )
    assert ei.value.status_code == 400


def test_step_exports_too_many_rejected():
    with pytest.raises(APIError) as ei:
        validate_workflow_fields(
            name="wf", description=None,
            steps=_steps_with_exports([f"f{i}.txt" for i in range(21)]),
        )
    assert ei.value.status_code == 400
