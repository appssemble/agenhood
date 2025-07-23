"""Route-inventory meta-gate: fail when an HTTP service grows a route with no
contract test. Pure duck-typing on ``app.routes`` so this ships in the
``agentcore`` runtime wheel without importing fastapi/starlette."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

RoutePair = tuple[str, str]  # (METHOD, path); METHOD == "WEBSOCKET" for ws routes

_SKIP_METHODS = {"HEAD", "OPTIONS"}


def _framework_defaults(app: Any) -> set[str]:
    """The openapi/docs/redoc paths FastAPI auto-registers, read off the app so
    a service with custom docs URLs (e.g. control-plane's /v1/docs) is handled."""
    paths: set[str] = set()
    for attr in ("openapi_url", "docs_url", "redoc_url"):
        value = getattr(app, attr, None)
        if value:
            paths.add(value)
    docs = getattr(app, "docs_url", None)
    if docs:
        paths.add(docs.rstrip("/") + "/oauth2-redirect")
    return paths


def _walk(routes: Iterable[Any], prefix: str, defaults: set[str]) -> set[RoutePair]:
    found: set[RoutePair] = set()
    for route in routes:
        path = prefix + getattr(route, "path", "")
        # FastAPI 0.138 / Starlette 1.3: include_router() may leave a lazy
        # `_IncludedRouter` wrapper in app.routes whose children live under
        # `.original_router.routes`, NOT `.routes`. Without this branch the
        # enumerator silently finds ZERO real routes and the gate passes
        # vacuously (index reconciliation §2 — binding). Recurses `routes` if
        # present (plain Mount / sub-app), else falls back to
        # `original_router.routes` (lazy _IncludedRouter wrapper).
        included = getattr(route, "original_router", None)
        sub = getattr(route, "routes", None) or getattr(included, "routes", None)
        if sub:  # Mount / sub-application / included router: recurse
            # _IncludedRouter stores its effective prefix in include_context.prefix
            # rather than as a .path attribute; fold it into the recursion prefix.
            ctx = getattr(route, "include_context", None)
            ctx_prefix = getattr(ctx, "prefix", "") or ""
            found |= _walk(sub, path + ctx_prefix, defaults)
            continue
        if path in defaults:
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            # Websocket route: has a path but methods is None.
            if path:
                found.add(("WEBSOCKET", path))
            continue
        for method in methods:
            upper = method.upper()
            if upper in _SKIP_METHODS:
                continue
            found.add((upper, path))
    return found


def collect_routes(app: Any) -> set[RoutePair]:
    """Every ``(METHOD, path)`` a client can call on ``app``, excluding the
    framework's openapi/docs/redoc routes and auto HEAD/OPTIONS. Websocket
    routes are reported as ``("WEBSOCKET", path)``."""
    return _walk(app.routes, "", _framework_defaults(app))


def _norm(pairs: Iterable[RoutePair]) -> set[RoutePair]:
    return {(method.upper(), path) for method, path in pairs}


def assert_routes_covered(
    app: Any,
    tested_paths: Iterable[RoutePair],
    allow: Iterable[RoutePair] = (),
) -> None:
    """Fail if any registered route lacks a tested entry and is not on the
    reviewed ``allow`` list. Also fails if an ``allow`` entry no longer matches
    a real route, so a stale/typo'd allow cannot silently hide a new gap."""
    registered = collect_routes(app)
    tested = _norm(tested_paths)
    allowed = _norm(allow)

    stale = allowed - registered
    assert not stale, (
        "route allow-list entries match no registered route "
        f"(stale or typo'd): {sorted(stale)}"
    )

    missing = registered - tested - allowed
    assert not missing, (
        f"{len(missing)} registered route(s) have no contract test and are not "
        f"on the reviewed allow-list: {sorted(missing)}"
    )
