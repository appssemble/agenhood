from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agentcore.models import Event, ShimTaskRequest
from shim.eventlog import EventLog

OnEvent = Callable[[str, Event], Awaitable[None]] | None


class TaskRunner:
    """Runs one task: resolves the driver, emits+persists events, writes status.

    The vanilla driver (and fakes in tests) accept a keyword-only `workspace`;
    the runner passes the real workspace path.
    """

    def __init__(
        self,
        *,
        request: ShimTaskRequest,
        workspace: str,
        drivers: dict[str, Any],
        on_event: OnEvent = None,
    ) -> None:
        self.request = request
        self.workspace = workspace
        self._drivers = drivers
        self._on_event = on_event
        self.cancel = asyncio.Event()
        self.log = EventLog(workspace=workspace, task_id=request.task_id)

        self.status: str = "running"
        self.started_at: str = datetime.now(UTC).isoformat()
        self.finished_at: str | None = None
        self.result: Any | None = None
        self.error: dict[str, Any] | None = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.iterations = 0

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "token_update":
            self.tokens_in = payload.get("tokens_in", self.tokens_in)
            self.tokens_out = payload.get("tokens_out", self.tokens_out)
        if event_type == "iteration_started":
            self.iterations = payload.get("iteration", self.iterations)
        event = self.log.append(event_type, payload)
        if self._on_event is not None:
            await self._on_event(self.request.task_id, event)

    async def run(self) -> None:
        driver = self._drivers.get(self.request.config.driver)
        if driver is None:
            await self._fail_unknown_driver()
            return
        try:
            result = await driver.run(
                task=self.request.task,
                config=self.request.config,
                limits=self.request.limits,
                credential=self.request.llm_credential,
                emit=self._emit,
                cancel=self.cancel,
                credential_kind=self.request.credential_kind,
                credential_meta=self.request.credential_meta,
                workspace=self.workspace,
                skills=self.request.skills,
                mcp_servers=self.request.mcp_servers,
                session_id=self.request.session_id,
                session_is_continuation=self.request.session_is_continuation,
                env=self.request.env,
            )
        except Exception as e:  # noqa: BLE001 — surface driver crash as failed status
            await self._finish_status(
                "failed", None, {"code": "driver_error", "message": str(e)}
            )
            return
        # The vanilla driver already emits its terminal status_change; derive
        # the runner's terminal fields from the TaskResult and reconcile status.
        self._finalize_from_result(result)

    def _finalize_from_result(self, result: Any) -> None:
        if result.success:
            self.status = "completed"
            self.error = None
        else:
            reason = result.reason or ""
            if reason == "cancelled":
                self.status = "cancelled"
            elif reason == "timeout":
                self.status = "timed_out"
            else:
                self.status = "failed"
            self.error = {"code": reason, "message": reason} if reason else None
        self.result = result.output
        self.finished_at = datetime.now(UTC).isoformat()
        self.log.write_status(self._status_dict())

    async def _fail_unknown_driver(self) -> None:
        msg = f"unknown driver: {self.request.config.driver}"
        await self._finish_status(
            "failed", None, {"code": "validation_error", "message": msg}
        )

    async def _finish_status(
        self, to: str, result: Any, error: dict[str, Any] | None
    ) -> None:
        await self._emit(
            "status_change",
            {"from": "running", "to": to, "result": result, "error": error},
        )
        self.status = to
        self.result = result
        self.error = error
        self.finished_at = datetime.now(UTC).isoformat()
        self.log.write_status(self._status_dict())

    def _status_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.request.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "iterations_used": self.iterations,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "result": self.result,
            "error": self.error,
        }

    def request_cancel(self) -> None:
        self.cancel.set()
