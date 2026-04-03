from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _put_rule(client, conn_id: str, *, priority: int = 50) -> str:
    """Helper: PUT a valid routing rule and return the new rule id."""
    r = client.put("/v1/routing-rules", json={
        "connection_id": conn_id,
        "tenant_id": "ten_1",
        "priority": priority,
        "match": {"event": "app_mention"},
        "target": {"container_id": "cnt_1"},
        "surface": ["result"],
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_delete_routing_rule_removes_it(client_with_conn):
    """DELETE /v1/routing-rules/{rule_id} returns {"status": "deleted"} and the
    rule is gone from the GET list for that connection."""
    client, conn_id = client_with_conn
    rule_id = _put_rule(client, conn_id)

    d = client.delete(f"/v1/routing-rules/{rule_id}")
    assert d.status_code == 200
    assert d.json() == {"status": "deleted"}

    # The rule must no longer appear in the list.
    rules = client.get("/v1/routing-rules",
                       params={"connection_id": conn_id}).json()["routing_rules"]
    assert all(r["id"] != rule_id for r in rules)


def test_delete_routing_rule_only_removes_target(client_with_conn):
    """Deleting one rule leaves sibling rules intact (no over-deletion)."""
    client, conn_id = client_with_conn
    keep_id = _put_rule(client, conn_id, priority=10)
    delete_id = _put_rule(client, conn_id, priority=20)

    d = client.delete(f"/v1/routing-rules/{delete_id}")
    assert d.status_code == 200
    assert d.json() == {"status": "deleted"}

    rules = client.get("/v1/routing-rules",
                       params={"connection_id": conn_id}).json()["routing_rules"]
    ids = {r["id"] for r in rules}
    assert keep_id in ids
    assert delete_id not in ids


def test_delete_routing_rule_unknown_id_is_noop(client_with_conn):
    """DELETE on a non-existent rule_id is a no-op: returns 200 with
    {"status": "deleted"} (the handler deletes 0 rows, no 404)."""
    client, _conn_id = client_with_conn
    d = client.delete("/v1/routing-rules/rul_does_not_exist")
    assert d.status_code == 200
    assert d.json() == {"status": "deleted"}
