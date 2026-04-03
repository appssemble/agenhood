from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_rule_requires_binding(client_with_conn):
    client, conn_id = client_with_conn
    r = client.put("/v1/routing-rules", json={
        "connection_id": conn_id, "tenant_id": "ten_1", "priority": 10,
        "match": {"event": "app_mention", "channel": "#support"},
        "target": {"container_id": "cnt_missing"},
        "surface": ["reasoning", "result"],
    })
    assert r.status_code == 400  # no enabled binding for cnt_missing


def test_rule_with_valid_binding_succeeds(client_with_conn):
    client, conn_id = client_with_conn
    # cnt_1 has an enabled binding seeded by the fixture
    r = client.put("/v1/routing-rules", json={
        "connection_id": conn_id, "tenant_id": "ten_1", "priority": 50,
        "match": {"event": "app_mention"},
        "target": {"container_id": "cnt_1"},
        "surface": ["reasoning", "result"],
    })
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    rule_id = data["id"]

    g = client.get("/v1/routing-rules", params={"connection_id": conn_id})
    assert g.status_code == 200
    rules = g.json()["routing_rules"]
    assert any(rule["id"] == rule_id for rule in rules)
