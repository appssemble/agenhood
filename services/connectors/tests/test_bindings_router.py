from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_put_then_get_binding(client_with_conn):
    client, conn_id = client_with_conn
    r = client.put("/v1/bindings", json={
        "connection_id": conn_id, "container_id": "cnt_1", "tenant_id": "ten_1",
        "enabled": True, "resource_filters": {"channels": ["#support"]},
    })
    assert r.status_code == 200
    g = client.get("/v1/bindings", params={"container_id": "cnt_1"})
    assert g.status_code == 200
    assert g.json()["bindings"][0]["resource_filters"] == {"channels": ["#support"]}
