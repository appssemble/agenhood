"""Vanilla driver — tool-use loop with done-tool, budgets, and event emission.

Spec §3.5.1 (loop), §3.6 (done tool), §3.8 (output resolution).
Self-registers into DRIVERS via register().
"""

from __future__ import annotations

import asyncio
import os
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
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody, TaskResult
from agentcore.tools.base import TOOLS, ToolContext, ToolSpec

# ---------------------------------------------------------------------------
# Done tool spec — always injected by the driver, NOT in TOOLS / config.tools
# ---------------------------------------------------------------------------

DONE_TOOL = ToolSpec(
    name="done",
    description=(
        "Signal task completion. Call with success=true and an output, or "
        "success=false with a reason if you cannot accomplish the task."
    ),
    input_schema={
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "output": {
                "description": "Result. Must match the task output schema when "
                "the task output type is structured."
            },
            "reason": {"type": "string"},
        },
    },
)

# ---------------------------------------------------------------------------
# Output resolution (spec §3.8)
# ---------------------------------------------------------------------------


def _list_workspace_files(workspace: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ws = os.path.realpath(workspace)
    for dirpath, dirnames, filenames in os.walk(ws):
        if ".agent-runtime" in dirnames:
            dirnames.remove(".agent-runtime")
        for name in filenames:
            full = os.path.join(dirpath, name)
            out.append(
                {"path": os.path.relpath(full, ws), "size": os.path.getsize(full)}
            )
    return out


def resolve_output(
    done_input: dict[str, Any], task: TaskBody, workspace: str
) -> tuple[bool, Any]:
    """Resolve a `done` call per spec §3.8.

    Returns (accepted, payload). When accepted is False, payload is an error
    string to feed back to the model (the loop continues).
    """
    success = bool(done_input.get("success", False))
    if not success:
        return True, {"success": False, "reason": done_input.get("reason", "")}

    output = done_input.get("output")

    if task.output.type == "structured":
        schema = task.output.json_schema or {}
        try:
            jsonschema.validate(instance=output, schema=schema)
        except jsonschema.ValidationError as e:
            return False, f"output does not match the required schema: {e.message}"
        return True, {"success": True, "output": output}

    if task.output.type == "files":
        return True, {
            "success": True,
            "output": output,
            "files": _list_workspace_files(workspace),
        }

    # text
    return True, {"success": True, "output": output}


# ---------------------------------------------------------------------------
# Driver constants
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are a capable, autonomous research and production assistant. You work "
    "in a sandboxed Linux workspace and finish tasks by producing files and a "
    "clear result. Use your tools deliberately and cite sources where relevant."
)

MAX_TOKENS_PER_CALL = 4096


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_spec_to_anthropic(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
    }


def enabled_tool_specs(config: AgentConfig) -> list[ToolSpec]:
    """Return enabled tool ToolSpecs (from TOOLS) plus DONE_TOOL, in order."""
    specs: list[ToolSpec] = []
    for name in config.tools:
        tool = TOOLS.get(name)
        if tool is not None:
            specs.append(tool.spec)
    specs.append(DONE_TOOL)
    return specs


# ---------------------------------------------------------------------------
# VanillaDriver — the full tool-use loop (spec §3.5.1)
# ---------------------------------------------------------------------------


class VanillaDriver:
    name = "vanilla"
    capabilities = DriverCapabilities(
        supports_tools=True,
        supports_structured_output=True,
        supports_cancel=True,
        requires_image_feature=None,
    )
    default_template = DriverTemplate(
        driver="vanilla",
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        available_tools=[
            "read_file", "write_file", "edit_file", "list_files",
            "delete_file", "bash", "python", "web_search", "web_fetch",
        ],
        tools_user_editable=True,
        supports_context=True,
    )

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

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
        skills: list[Any] | None = None,  # opencode-only; ignored here
        mcp_servers: list[Any] | None = None,  # opencode/codex-only; ignored here
        session_id: str | None = None,
        session_is_continuation: bool = False,
        env: dict[str, str] | None = None,
    ) -> TaskResult:
        from agentcore.prompt import assemble_system_prompt

        await emit("task_started", {"driver": self.name, "model": config.model})

        specs = enabled_tool_specs(config)
        system_prompt = assemble_system_prompt(
            config=config,
            driver_default_system_prompt=DEFAULT_SYSTEM_PROMPT,
            tool_specs=specs,
            task=task,
            limits=limits,
        )
        anthropic_tools = [_tool_spec_to_anthropic(s) for s in specs]
        tool_ctx = ToolContext(workspace=workspace, cancel=cancel, env=env or {})

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
        iterations = 0
        tokens_in = 0
        tokens_out = 0
        start = time.monotonic()

        async def _terminal(
            to: str, code: str | None, output: Any = None
        ) -> TaskResult:
            if code is not None:
                await emit("log", {"level": "warn", "message": code, "data": {}})
            err: dict[str, Any] | None = (
                {"code": code, "message": code} if code else None
            )
            if session_id is not None:
                write_session_state(workspace, self.name, session_id, {"messages": messages})
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
            # Check all limits and cancellation before each iteration.
            if cancel.is_set():
                return await _terminal("cancelled", "cancelled")
            if (tokens_in + tokens_out) >= limits.max_tokens:
                return await _terminal("failed", "token_budget_exhausted")
            if (time.monotonic() - start) >= limits.timeout_seconds:
                return await _terminal("timed_out", "timeout")
            if iterations >= limits.max_iterations:
                return await _terminal("failed", "iteration_limit")

            await emit("iteration_started", {"iteration": iterations + 1})
            response = await self._llm.create(
                model=config.model,
                system=system_prompt,
                messages=messages,
                tools=anthropic_tools,
                max_tokens=MAX_TOKENS_PER_CALL,
                credential=credential,
            )
            tokens_in += response.tokens_in
            tokens_out += response.tokens_out
            await emit("token_update", {"tokens_in": tokens_in, "tokens_out": tokens_out})
            await emit("assistant_message", {"content": response.content})

            tool_uses = [b for b in response.content if b.get("type") == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            if not tool_uses:
                # No tool call — nudge the model to call done.
                messages.append(
                    {
                        "role": "user",
                        "content": "You must call the `done` tool to finish.",
                    }
                )
                iterations += 1
                continue

            tool_results: list[dict[str, Any]] = []
            done_accepted = False
            done_payload: Any = None

            for tu in tool_uses:
                await emit(
                    "tool_call",
                    {
                        "tool_use_id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    },
                )

                if tu["name"] == "done":
                    accepted, payload = resolve_output(tu["input"], task, workspace)
                    if accepted:
                        await emit(
                            "tool_result",
                            {
                                "tool_use_id": tu["id"],
                                "ok": True,
                                "content": "accepted",
                                "duration_ms": 0,
                            },
                        )
                        done_accepted = True
                        done_payload = payload
                        break  # done is always alone; stop processing tool_uses

                    # Invalid structured output — feed error back, loop continues.
                    await emit(
                        "tool_result",
                        {
                            "tool_use_id": tu["id"],
                            "ok": False,
                            "content": payload,
                            "duration_ms": 0,
                        },
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": payload,
                            "is_error": True,
                        }
                    )
                    continue

                tool = TOOLS.get(tu["name"])
                if tool is None:
                    msg = f"unknown tool: {tu['name']}"
                    await emit(
                        "tool_result",
                        {
                            "tool_use_id": tu["id"],
                            "ok": False,
                            "content": msg,
                            "duration_ms": 0,
                        },
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": msg,
                            "is_error": True,
                        }
                    )
                    continue

                res = await tool.run(tu["input"], tool_ctx)
                await emit(
                    "tool_result",
                    {
                        "tool_use_id": tu["id"],
                        "ok": res.ok,
                        "content": res.content,
                        "duration_ms": res.duration_ms,
                    },
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": res.content,
                        "is_error": not res.ok,
                    }
                )

            if done_accepted:
                if done_payload.get("success") is False:
                    return await _terminal(
                        "failed",
                        done_payload.get("reason") or "model_reported_failure",
                        output=done_payload,
                    )
                return await _terminal("completed", None, output=done_payload)

            messages.append({"role": "user", "content": tool_results})
            iterations += 1


# ---------------------------------------------------------------------------
# Self-register with the real Anthropic client by default.
# The shim injects the configured client; this module-level instance is what
# the registry exposes for capability/template lookup.
# Tests instantiate VanillaDriver directly with a scripted LLM.
# ---------------------------------------------------------------------------

from agentcore.llm.anthropic import AnthropicClient  # noqa: E402

register(VanillaDriver(llm=AnthropicClient()))
