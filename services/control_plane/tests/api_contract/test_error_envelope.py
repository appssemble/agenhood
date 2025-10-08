"""Error-envelope uniformity gate (Unit C, Task 4).

Asserts that every APIError-derived response from the control-plane API uses
the canonical envelope shape::

    {"error": {"code": str, "message": str[, "field": str]}}

The ONE deliberate exception:  422 RequestValidationError uses FastAPI's
``{"detail": [...]}`` shape (NOT the envelope) with ``input`` and ``ctx``
stripped as a secret-leak guard.  This module encodes that exception so any
future *third* shape triggers a test failure.

Coverage:
- Constructor-level: unauthorized / not_found / too_many_tasks /
  validation_error / container_not_runnable → envelope via api_error_handler
- HTTP 401: GET /v1/containers with no credentials → envelope
- HTTP 422: POST /v1/auth/login with bad body → {detail:[...]} (known exception)
- HTTP 500: unhandled RuntimeError from a route dependency → envelope
"""
from __future__ import annotations

import json

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from control_plane.errors import (
    APIError,
    api_error,
    api_error_handler,
    container_not_runnable,
    not_found,
    too_many_tasks,
    unauthorized,
    validation_error,
)
from tests.api_contract import contracts as C

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Envelope predicate
# ---------------------------------------------------------------------------


def _is_envelope(body: dict) -> bool:  # type: ignore[type-arg]
    """Return True iff *body* conforms to the canonical error envelope."""
    return (
        set(body) == {"error"}
        and isinstance(body["error"], dict)
        and isinstance(body["error"].get("code"), str)
        and isinstance(body["error"].get("message"), str)
        and set(body["error"]) <= {"code", "message", "field"}
    )


# ---------------------------------------------------------------------------
# Constructor-level: every APIError constructor emits the envelope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ctor",
    [
        unauthorized,
        not_found,
        too_many_tasks,
        lambda: validation_error("bad", field="x"),
        lambda: container_not_runnable("nope"),
        lambda: api_error(403, "forbidden", "x"),  # 403 role-deny path (brief-required)
    ],
)
async def test_apierror_constructors_emit_envelope(ctor) -> None:  # type: ignore[no-untyped-def]
    """Each APIError convenience constructor → envelope via api_error_handler."""
    exc = ctor()
    assert isinstance(exc, APIError)
    resp = await api_error_handler(Request({"type": "http"}), exc)
    body = json.loads(bytes(resp.body))
    assert _is_envelope(body), f"Not an envelope: {body!r}"
    assert resp.status_code == exc.status_code


# ---------------------------------------------------------------------------
# HTTP 401 — no credentials → envelope with code "unauthorized"
# ---------------------------------------------------------------------------


async def test_401_response_is_envelope() -> None:
    """GET /v1/containers with no credentials returns envelope + code=unauthorized."""
    app = C.make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/v1/containers")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}; body={r.text!r}"
    body = r.json()
    assert _is_envelope(body), f"401 response is not an envelope: {body!r}"
    assert body["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# HTTP 422 — the ONE documented exception: FastAPI {detail:[...]} shape
# ---------------------------------------------------------------------------


async def test_422_is_the_documented_exception_and_strips_secrets() -> None:
    """422 uses {detail:[...]} (NOT the envelope) and never echoes input/ctx.

    This is the only status code whose shape is deliberately different from
    the envelope.  The test encodes it so a future third shape cannot slip in
    silently.
    """
    app = C.make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/v1/auth/login", json={"email": "not-an-email"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}; body={r.text!r}"
    body = r.json()
    assert set(body) == {"detail"}, (
        f"422 body must have only 'detail' key; got keys={set(body)!r}"
    )
    assert isinstance(body["detail"], list), (
        f"422 body['detail'] must be a list; got {type(body['detail'])}"
    )
    for err in body["detail"]:
        assert "input" not in err, f"Secret-leak: 'input' present in 422 error: {err!r}"
        assert "ctx" not in err, f"Secret-leak: 'ctx' present in 422 error: {err!r}"


# ---------------------------------------------------------------------------
# HTTP 500 — unhandled RuntimeError → internal_error envelope
# ---------------------------------------------------------------------------


async def test_500_is_internal_error_envelope() -> None:
    """An unhandled exception from a route dependency maps to the envelope.

    The internal_error handler (registered in create_app) must catch any
    Exception and return {"error":{"code":"internal_error","message":"..."}}.
    We trigger it by overriding resolve_principal to raise RuntimeError.
    """
    app = C.make_app()
    from control_plane.auth import principal as pmod

    async def _boom() -> None:
        raise RuntimeError("kaboom")

    app.dependency_overrides[pmod.resolve_principal] = _boom
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as c:
            r = await c.get("/v1/containers")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 500, f"Expected 500, got {r.status_code}; body={r.text!r}"
    assert r.json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }, f"500 envelope mismatch: {r.text!r}"
