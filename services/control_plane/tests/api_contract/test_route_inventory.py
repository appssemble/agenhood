"""Route-inventory meta-gate + per-route contract parametrized tests (Unit C, Task 2).

test_every_registered_route_has_a_contract:
    Meta-gate: enumerates the live app's routes via agentcore.testing.route_inventory
    and asserts every route is either in CONTRACTS or in ALLOW.  A new route that
    is not registered here causes this test to fail immediately, naming the gap.

test_route_contract[METHOD /path]:
    Parametrized over every CONTRACTS entry.  Sends a no-credential request and
    asserts the contract kind:
      auth     → 401 + {"error":{"code":"unauthorized",...}}
      public   → any status except 401
      redirect → 307 or 308 + Location header

Design notes
    - No real DB is needed: auth routes fail at resolve_principal before any DB
      query (SQLAlchemy AsyncSession is lazy — no connection opened unless a
      statement executes, and resolve_from_inputs returns None immediately when
      no bearer/cookie are present).
    - Public/redirect routes likewise need no DB (logout has no cookie → no DB
      query; healthz catches the connection error and returns 503; redirects
      have no dependencies at all).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests.api_contract import contracts as C

pytestmark = pytest.mark.unit


def test_every_registered_route_has_a_contract() -> None:
    """Meta-gate: a new route without a CONTRACTS entry fails here.

    Uses agentcore.testing.route_inventory.assert_routes_covered which:
      1. Calls collect_routes(app) to get all registered (METHOD, path) pairs
         (excluding framework openapi/docs/redoc routes via _framework_defaults).
      2. Verifies every registered route is either in `tested` or in `allow`.
      3. Verifies every `allow` entry still matches a real registered route
         (stale/typo'd allow entries fail, so they cannot silently hide gaps).
    """
    from agentcore.testing.route_inventory import assert_routes_covered

    app = C.make_app()
    tested = {(m, path) for (m, path, _url, _kind) in C.CONTRACTS}
    assert_routes_covered(app, tested, allow=C.ALLOW)


@pytest.mark.parametrize("entry", C.CONTRACTS, ids=lambda e: f"{e[0]} {e[1]}")
async def test_route_contract(entry: tuple[str, str, str, str]) -> None:
    """Per-route contract: no-credential request → expected status for each kind.

    kind="auth"     → 401 Unauthorized (resolve_principal raises before handler)
    kind="public"   → any non-401 (route has no auth dependency)
    kind="redirect" → 307 or 308 with Location header (redirect before any auth)
    """
    method, _path_template, sample_url, kind = entry
    app = C.make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.request(method, sample_url, follow_redirects=False)

    if kind == "auth":
        assert r.status_code == 401, (
            f"{method} {sample_url} expected 401 but got {r.status_code}"
        )
        body = r.json()
        assert body.get("error", {}).get("code") == "unauthorized", (
            f"{method} {sample_url} body={body!r}"
        )
    elif kind == "redirect":
        assert r.status_code in (307, 308), (
            f"{method} {sample_url} expected 307/308 but got {r.status_code}"
        )
        assert "location" in {k.lower() for k in r.headers}, (
            f"{method} {sample_url} missing Location header"
        )
    else:  # public
        assert r.status_code != 401, (
            f"{method} {sample_url} expected non-401 but got {r.status_code}"
        )
