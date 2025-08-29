from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_plane.routers import health


def _client(check):
    app = FastAPI()
    app.include_router(health.router)
    app.dependency_overrides[health.db_check] = lambda: check
    return TestClient(app)


def test_healthz_returns_200_when_db_ok():
    async def ok_check() -> None:
        return None  # SELECT 1 succeeded
    client = _client(ok_check)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_returns_503_when_db_check_raises():
    async def failing_check() -> None:
        raise RuntimeError("connection refused")
    client = _client(failing_check)
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
