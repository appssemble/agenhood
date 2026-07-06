from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field: str | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


def _envelope(code: str, message: str, field: str | None) -> dict:  # type: ignore[type-arg]
    err: dict = {"code": code, "message": message}  # type: ignore[type-arg]
    if field is not None:
        err["field"] = field
    return {"error": err}


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.field),
    )


async def request_validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 handler that never echoes the request body back to the client.

    FastAPI's default handler returns each error with an ``input`` key holding
    the submitted value — when one field of a body fails validation, the whole
    body object is echoed for ``missing``-field errors.  Bodies here can carry
    secrets (git PATs, LLM credentials), so we strip ``input`` and ``ctx`` and
    keep only the location/type/message of each error.
    """
    detail = [
        {k: v for k, v in err.items() if k not in ("input", "ctx")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


# Convenience constructors for the canonical codes used in this unit.
def unauthorized(message: str = "missing or invalid credentials") -> APIError:
    return APIError(401, "unauthorized", message)


def not_found(message: str = "resource not found") -> APIError:
    return APIError(404, "not_found", message)


def validation_error(message: str, field: str | None = None) -> APIError:
    return APIError(400, "validation_error", message, field)


def container_not_runnable(message: str) -> APIError:
    return APIError(409, "container_not_runnable", message)


def too_many_tasks(message: str = "container is at its concurrent-task limit") -> APIError:
    return APIError(429, "too_many_tasks", message)


def session_driver_mismatch(message: str) -> APIError:
    return APIError(409, "session_driver_mismatch", message)


def session_busy(message: str = "session already has a task in flight") -> APIError:
    return APIError(409, "session_busy", message)


def api_error(status_code: int, code: str, message: str, field: str | None = None) -> APIError:
    """Generic constructor used by auth/ modules (plan §Task0 §Step5)."""
    return APIError(status_code, code, message, field)


# Alias used by lifecycle/variant modules for semantic clarity.
Conflict = APIError
