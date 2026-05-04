import pytest
from control_plane.models_db import workflows, workflow_runs

pytestmark = pytest.mark.unit


def test_workflow_tables_have_expected_columns():
    assert set(workflows.c.keys()) == {
        "id", "tenant_id", "name", "description", "steps",
        "created_by", "created_at", "updated_at",
    }
    assert set(workflow_runs.c.keys()) == {
        "id", "workflow_id", "tenant_id", "status", "cursor", "current_task_id",
        "step_count", "error_step", "error_message", "steps", "trigger_source",
        "scheduled_task_id", "started_at", "step_started_at", "ended_at",
    }
