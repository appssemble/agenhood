from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from control_plane import analytics_service
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.routers.containers import _session
from control_plane.schemas import BreakdownGroupOut, UsageBucketOut

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed", seed_api_key="tk_live_seed", seed_llm_api_key="",
    agent_image_tag="test", internal_network="test",
    readyz_timeout_seconds=1.0, shim_port=8080,
)
app = create_app(_SETTINGS)

MEMBER = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_m")
STAFF = Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_s")


def _use(principal: Principal) -> None:
    app.dependency_overrides[resolve_principal] = lambda: principal
    app.dependency_overrides[_session] = lambda: object()  # service is mocked


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_usage_happy_path_wraps_envelope(monkeypatch) -> None:
    async def fake_usage(session, *, tenant_id, start, end, interval):
        assert tenant_id == "ten_1" and interval == "day"
        return [UsageBucketOut(start="2026-05-27T00:00:00+00:00",
                               tokens_in=5, tokens_out=2, tasks=1, iterations=3)]
    monkeypatch.setattr(analytics_service, "usage_series", fake_usage)
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/usage",
                  params={"from": "2026-05-27T00:00:00+00:00", "interval": "day"})
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "2026-05-27T00:00:00+00:00"
    assert body["interval"] == "day"
    assert body["series"][0]["tokens_in"] == 5


def test_usage_rejects_bad_interval() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/usage",
                  params={"from": "2026-05-27T00:00:00+00:00", "interval": "week"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"


def test_usage_rejects_naive_from() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/usage",
                  params={"from": "2026-05-27T00:00:00", "interval": "day"})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "from"


def test_breakdown_happy_path(monkeypatch) -> None:
    async def fake_breakdown(session, *, tenant_id, start, end, by):
        assert by == "container"
        return [BreakdownGroupOut(key="c1", label="bot",
                                  tokens_in=10, tokens_out=4, tasks=2, iterations=6)]
    monkeypatch.setattr(analytics_service, "breakdown", fake_breakdown)
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/breakdown",
                  params={"from": "2026-05-27T00:00:00+00:00", "by": "container"})
    assert r.status_code == 200
    assert r.json()["groups"][0]["label"] == "bot"


def test_breakdown_rejects_bad_by() -> None:
    _use(MEMBER)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/breakdown",
                  params={"from": "2026-05-27T00:00:00+00:00", "by": "tenant"})
    assert r.status_code == 400


def test_usage_forbidden_for_staff_principal() -> None:
    _use(STAFF)
    with TestClient(app) as c:
        r = c.get("/v1/analytics/usage",
                  params={"from": "2026-05-27T00:00:00+00:00", "interval": "day"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
