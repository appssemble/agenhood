"""Canonical error codes, exception types, and the JSON error envelope (index §6)."""

from __future__ import annotations

import typing
from typing import Any, Literal

# Canonical error codes — use these verbatim across all units (index §6).
ErrorCode = Literal[
    "validation_error",
    "no_credential",
    "container_not_runnable",
    "too_many_tasks",
    "running_capacity_exhausted",
    "max_containers_reached",
    "external_id_in_use",
    "too_many_requests",
    "shim_unavailable",
    "unauthorized",
    "forbidden",
    "not_found",
]

ERROR_CODES: frozenset[str] = frozenset(typing.get_args(ErrorCode))


def error_envelope(
    code: ErrorCode, message: str, field: str | None = None
) -> dict[str, Any]:
    """Build the standard error envelope: {"error": {"code", "message", "field?"}}."""
    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code: {code!r}")
    body: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        body["field"] = field
    return {"error": body}


class AgentRuntimeError(Exception):
    """Base for all runtime errors. Subclasses set ``code``; ``field`` is optional."""

    code: ErrorCode

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def to_envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, self.field)


class ValidationError(AgentRuntimeError):
    code: ErrorCode = "validation_error"


class NoCredentialError(AgentRuntimeError):
    code: ErrorCode = "no_credential"


class ContainerNotRunnableError(AgentRuntimeError):
    code: ErrorCode = "container_not_runnable"


class TooManyTasksError(AgentRuntimeError):
    code: ErrorCode = "too_many_tasks"


class RunningCapacityExhaustedError(AgentRuntimeError):
    code: ErrorCode = "running_capacity_exhausted"


class MaxContainersReachedError(AgentRuntimeError):
    code: ErrorCode = "max_containers_reached"


class UnauthorizedError(AgentRuntimeError):
    code: ErrorCode = "unauthorized"


class ForbiddenError(AgentRuntimeError):
    code: ErrorCode = "forbidden"


class NotFoundError(AgentRuntimeError):
    code: ErrorCode = "not_found"
