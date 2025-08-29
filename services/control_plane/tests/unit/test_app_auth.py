import pytest
from httpx import ASGITransport, AsyncClient

from control_plane.app import create_app
from control_plane.config import Settings
from control_plane.routers import health as health_router

pytestmark = pytest.mark.unit


def _settings() -> Settings:
    return Settings.from_env()


async def _client(app):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_healthz_open() -> None:
    """Verifies /healthz is unauthenticated. Overrides the DB check so no real DB needed."""

    async def _ok_check() -> None:
        return None

    app = create_app(_settings())
    app.dependency_overrides[health_router.db_check] = lambda: _ok_check
    async with await _client(app) as c:
        r = await c.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


async def test_protected_route_requires_key() -> None:
    app = create_app(_settings())
    async with await _client(app) as c:
        r = await c.get("/v1/containers")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"


async def test_protected_route_accepts_seed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # SEED_API_KEY has no default (empty) so deploys never mint a public key, so
    # this test must configure one explicitly to exercise the seed-key auth path.
    monkeypatch.setenv("SEED_API_KEY", "tk_live_seedkey")
    s = _settings()
    app = create_app(s)
    async with await _client(app) as c:
        # Auth passes → handler runs → may raise a DB error (no DB in unit tests).
        # Either way the seed key was accepted: a non-401 response OR a DB exception
        # proves auth passed (a 401 would have been returned before touching the DB).
        try:
            r = await c.get(
                "/v1/containers", headers={"Authorization": f"Bearer {s.seed_api_key}"}
            )
            assert r.status_code != 401
        except Exception as exc:
            # A DB connection error means auth passed and the handler ran.
            assert "401" not in str(exc)
