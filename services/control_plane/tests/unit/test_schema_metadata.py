import pytest

from control_plane.models_db import metadata

pytestmark = pytest.mark.unit


def test_owned_tables_present():
    names = set(metadata.tables.keys())
    assert {"templates", "containers", "tasks", "events", "audit_log", "tenants"} <= names


def test_tasks_has_config_snapshot_and_body():
    cols = {c.name for c in metadata.tables["tasks"].columns}
    assert {"config_snapshot", "body", "driver", "model", "status"} <= cols


def test_events_pk_is_task_seq():
    pk = [c.name for c in metadata.tables["events"].primary_key.columns]
    assert pk == ["task_id", "seq"]


def test_audit_log_columns():
    cols = {c.name for c in metadata.tables["audit_log"].columns}
    expected = {
        "id", "actor_type", "actor_id", "action",
        "target_type", "target_id", "details", "ts",
    }
    assert expected <= cols
