import pytest

from connectors.tables import (  # noqa: F401
    action_log,
    connections,
    container_bindings,
    deliveries,
    metadata,
    routing_rules,
    webhook_events,
)

pytestmark = pytest.mark.unit


def test_all_tables_registered():
    names = set(metadata.tables.keys())
    assert {
        "connections", "container_bindings", "routing_rules",
        "deliveries", "webhook_events", "action_log",
    } <= names


def test_connections_has_token_columns():
    cols = {c.name for c in connections.columns}
    assert {"access_token_ciphertext", "cp_api_key_ciphertext", "tenant_id", "provider"} <= cols


def test_deliveries_task_id_unique():
    assert deliveries.c.task_id.unique is True
