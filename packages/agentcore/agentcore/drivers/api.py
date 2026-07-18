"""api driver — single direct LLM call per task, no tools, high concurrency.

Built for pure-inference workloads (classify/extract/rewrite): one call per
task (plus a bounded retry loop for structured output), no workspace writes,
no subprocesses, so many tasks can run in parallel in one container. Reuses
vanilla's LLM routing; emits vanilla's event shapes so the console renders
tasks unchanged. Self-registers into DRIVERS via register().
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import jsonschema

from agentcore.drivers.base import (
    DriverCapabilities,
    DriverTemplate,
    EmitFn,
    register,
)
from agentcore.drivers.session_state import read_session_state, write_session_state
from agentcore.llm.base import LLMClient
from agentcore.llm.router import LLMRouter
from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimMcpServer,
    ShimSkill,
    TaskBody,
    TaskResult,
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a fast, precise assistant. Answer the request directly and "
    "completely in a single response. Do not narrate your process."
)

MAX_TOKENS_PER_CALL = 4096
MAX_ATTEMPTS = 3  # 1 initial call + 2 structured-output retries

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n|\n?```$")


def _parse_json_object(text: str) -> tuple[Any, str | None]:
    """Extract and parse the first JSON object in ``text``.

    Returns (parsed, None) on success or (None, error) on failure. Tolerates
    code fences and prose around the object: parses from the first ``{`` to
    the last ``}``.
    """
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None, "no JSON object found in the response"
    try:
        return json.loads(cleaned[start : end + 1]), None
    except ValueError as e:
        return None, f"invalid JSON: {e}"


def _system_prompt(config: AgentConfig, task: TaskBody) -> str:
    base = config.system_prompt or DEFAULT_SYSTEM_PROMPT
    if config.system_prompt_mode == "replace":
        return config.system_prompt
    sections: list[str] = [base]
    if task.output.type == "structured" and task.output.json_schema is not None:
        sections.append(
            "## Output\n"
            "Respond ONLY with a single JSON object matching this schema — "
            "no code fences, no prose before or after:\n"
            + json.dumps(task.output.json_schema)
        )
    ctx_parts: list[str] = []
    if config.context.variables:
        ctx_parts.append(
            "variables:\n" + json.dumps(config.context.variables, indent=2)
        )
    if config.context.text:
        ctx_parts.append(config.context.text)
    for path in config.context.files:
        ctx_parts.append(f"context file: {path}")
    if ctx_parts:
        sections.append("## Context\n" + "\n".join(ctx_parts))
    return "\n\n".join(sections)


class ApiDriver:
    name = "api"
    capabilities = DriverCapabilities(
        supports_tools=False,
        supports_structured_output=True,
        supports_cancel=True,
        requires_image_feature=None,
        supports_mcp=False,
        supports_skills=False,
    )
    default_template = DriverTemplate(
        driver="api",
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        available_tools=[],
        tools_user_editable=False,
        supports_context=True,
    )

    def __init__(
        self, llm: LLMClient | None = None, router: LLMRouter | None = None
    ) -> None:
        if llm is None and router is None:
            raise ValueError("ApiDriver needs an llm client or a router")
        self._llm = llm
        self._router = router

    def _route(self, model: str) -> tuple[LLMClient, str]:
        if self._router is not None:
            return self._router.route(model)
        assert self._llm is not None
        return self._llm, model

    async def run(
        self,
        *,
        task: TaskBody,
        config: AgentConfig,
        limits: ResolvedLimits,
        credential: str,
        emit: EmitFn,
        cancel: asyncio.Event,
        credential_kind: str = "api_key",
        credential_meta: dict[str, Any] | None = None,
        workspace: str = "/workspace",
        skills: list[ShimSkill] | None = None,
        mcp_servers: list[ShimMcpServer] | None = None,
        session_id: str | None = None,
        session_is_continuation: bool = False,
        env: dict[str, str] | None = None,
    ) -> TaskResult:
        await emit("task_started", {"driver": self.name, "model": config.model})

        try:
            client, wire_model = self._route(config.model)
        except ValueError as e:
            await emit(
                "status_change",
                {"from": "running", "to": "failed", "result": None,
                 "error": {"code": "unroutable_model", "message": str(e)}},
            )
            return TaskResult(success=False, reason="unroutable_model")

        if session_id is not None and session_is_continuation:
            state = read_session_state(workspace, self.name, session_id)
            if state is None:
                await emit(
                    "status_change",
                    {"from": "running", "to": "failed", "result": None,
                     "error": {"code": "session_state_lost",
                               "message": "session state file missing"}},
                )
                return TaskResult(success=False, reason="session_state_lost")
            messages: list[dict[str, Any]] = list(state.get("messages", []))
            messages.append({"role": "user", "content": task.prompt})
        else:
            messages = [{"role": "user", "content": task.prompt}]

        system = _system_prompt(config, task)
        structured = (
            task.output.type == "structured" and task.output.json_schema is not None
        )
        start = time.monotonic()
        tokens_in = 0
        tokens_out = 0
        attempts = 0

        async def _terminal(
            to: str, code: str | None, output: Any = None, message: str | None = None
        ) -> TaskResult:
            if code is not None:
                await emit("log", {"level": "warn", "message": code, "data": {}})
            err: dict[str, Any] | None = (
                {"code": code, "message": message or code} if code else None
            )
            if session_id is not None:
                write_session_state(
                    workspace, self.name, session_id, {"messages": messages}
                )
            await emit(
                "status_change",
                {"from": "running", "to": to, "result": output, "error": err},
            )
            return TaskResult(
                success=(to == "completed"),
                output=output,
                reason=(code if code else None),
            )

        while True:
            if cancel.is_set():
                return await _terminal("cancelled", "cancelled")
            if (tokens_in + tokens_out) >= limits.max_tokens:
                return await _terminal("failed", "token_budget_exhausted")
            remaining = limits.timeout_seconds - (time.monotonic() - start)
            if remaining <= 0:
                return await _terminal("timed_out", "timeout")
            if attempts >= MAX_ATTEMPTS:
                return await _terminal("failed", "invalid_structured_output")

            attempts += 1
            await emit("iteration_started", {"iteration": attempts})
            try:
                response = await asyncio.wait_for(
                    client.create(
                        model=wire_model,
                        system=system,
                        messages=messages,
                        tools=[],
                        max_tokens=MAX_TOKENS_PER_CALL,
                        credential=credential,
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                return await _terminal("timed_out", "timeout")
            except Exception as e:  # noqa: BLE001 — provider errors end the task
                return await _terminal("failed", "api_error", message=str(e))

            tokens_in += response.tokens_in
            tokens_out += response.tokens_out
            await emit(
                "token_update", {"tokens_in": tokens_in, "tokens_out": tokens_out}
            )
            await emit("assistant_message", {"content": response.content})
            messages.append({"role": "assistant", "content": response.content})

            text = "\n".join(
                b["text"] for b in response.content if b.get("type") == "text"
            )

            if not structured:
                return await _terminal(
                    "completed", None, output={"success": True, "output": text}
                )

            parsed, parse_err = _parse_json_object(text)
            if parse_err is None:
                try:
                    jsonschema.validate(
                        instance=parsed, schema=task.output.json_schema or {}
                    )
                except jsonschema.ValidationError as e:
                    parse_err = (
                        f"output does not match the required schema: {e.message}"
                    )
                else:
                    return await _terminal(
                        "completed", None, output={"success": True, "output": parsed}
                    )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Invalid output: {parse_err}. Respond ONLY with a single "
                        "JSON object matching the required schema — no code "
                        "fences, no prose."
                    ),
                }
            )


register(ApiDriver(router=LLMRouter()))
