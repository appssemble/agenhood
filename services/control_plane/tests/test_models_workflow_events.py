import pytest

from control_plane.models_db import workflow_events

pytestmark = pytest.mark.unit


def test_workflow_events_table_shape():
    assert set(workflow_events.c.keys()) == {
        "run_id", "seq", "type", "payload", "ts",
    }
    pk_cols = {c.name for c in workflow_events.primary_key.columns}
    assert pk_cols == {"run_id", "seq"}
