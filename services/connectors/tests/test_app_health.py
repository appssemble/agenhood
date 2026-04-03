import pytest
from fastapi.testclient import TestClient

from connectors.app import create_app

pytestmark = pytest.mark.unit


def test_healthz():
    client = TestClient(create_app(start_background=False))
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
