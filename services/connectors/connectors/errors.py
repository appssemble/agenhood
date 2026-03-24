from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.field = field


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    body = {"error": {"code": exc.code, "message": exc.message}}
    if exc.field:
        body["error"]["field"] = exc.field
    return JSONResponse(status_code=exc.status, content=body)
