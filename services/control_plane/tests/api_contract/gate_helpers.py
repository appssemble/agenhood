"""Gate-class introspection helpers for the RBAC meta-gate (Unit C, Task 3).

gate_class(route) -> str | None
    Walks the route's FastAPI dependant tree and returns the first gate
    dependency name found ("require_admin", "require_session_admin",
    "require_staff"), or None if no known gate is present.

null_session_overrides(app) -> dict
    Returns a dependency-overrides dict that maps each router's local
    ``_session`` function to a no-op null session so gate-passing requests
    don't crash on a real DB connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.routing import APIRoute

# The three named gate helpers defined in control_plane.auth.principal.
# Any route whose dependant tree contains one of these function names is
# "gate-classified".  A route with NONE of these names either is public,
# uses the bare resolve_principal dependency, or delegates to a custom
# wrapper (e.g. _principal in containers.py) — all of which are
# classified as "self-scoped" rather than role-gated.
GATE_DEPS = ("require_admin", "require_session_admin", "require_staff")


def gate_class(route: APIRoute) -> str | None:
    """Return the gate class for *route* by scanning its dependant tree.

    Walks every node of the FastAPI Dependant graph starting at
    route.dependant, collects the ``__name__`` of every callable, then
    returns the first name that appears in GATE_DEPS (priority order:
    require_admin > require_session_admin > require_staff).  Returns None
    if no known gate dependency is found.
    """
    names: set[str] = set()

    def walk(d: Any) -> None:
        if d.call:
            names.add(getattr(d.call, "__name__", ""))
        for sub in d.dependencies:
            walk(sub)

    walk(route.dependant)
    for g in GATE_DEPS:
        if g in names:
            return g
    return None


# ---------------------------------------------------------------------------
# Null session plumbing
# ---------------------------------------------------------------------------


class _NullResult:
    """Stub SQLAlchemy result that returns empty / zero for every accessor."""

    def mappings(self) -> _NullResult:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def fetchone(self) -> None:
        # Some handlers (e.g. containers recover staff branch) call fetchone()
        # on the raw result rather than .first(); return None so the handler
        # falls through to its not_found() raise.
        return None

    def scalar_one(self) -> int:
        return 0

    def scalar_one_or_none(self) -> None:
        return None


class _NullConn:
    """Stub async DB connection — every execute() returns a _NullResult."""

    async def execute(self, *a: Any, **k: Any) -> _NullResult:
        return _NullResult()

    async def commit(self) -> None:
        return None


async def _null_session() -> AsyncIterator[_NullConn]:
    """Yield a single _NullConn; used as a FastAPI dependency override."""
    yield _NullConn()


def null_session_overrides(app: Any) -> dict[Any, Any]:
    """Map each router's local ``_session`` dependency to a null session.

    Only routers that expose a module-level ``_session`` function are
    affected; routers that call ``request.app.state.session_factory``
    directly (e.g. mcp_servers, templates) are not overridden here —
    those endpoints are not used as representative gate-matrix endpoints
    so the override is unnecessary.

    Usage::

        app.dependency_overrides.update(null_session_overrides(app))
    """
    import control_plane.routers.admin as admin_mod
    import control_plane.routers.containers as containers_mod
    import control_plane.routers.credentials as cred_mod
    import control_plane.routers.users as users_mod

    out: dict[Any, Any] = {}
    for mod in (admin_mod, cred_mod, users_mod, containers_mod):
        sess = getattr(mod, "_session", None)
        if sess is not None:
            out[sess] = _null_session
    return out
