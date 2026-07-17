"""Vanilla driver — tool-use loop with done-tool, budgets, and event emission.

Spec §3.5.1 (loop), §3.6 (done tool), §3.8 (output resolution).
Self-registers into DRIVERS via register().
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Any

import jsonschema

from agentcore.drivers.base import (
    DriverCapabilities,
    DriverTemplate,
    EmitFn,
    register,
)
from agentcore.drivers.session_state import read_session_state, write_session_state
from agentcore.drivers.skill_tool import SkillTool, skills_dir
from agentcore.drivers.skills_md import write_skills
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
from agentcore.tools.base import TOOLS, Tool, ToolContext, ToolResult, ToolSpec

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

DEFAULT_TOOL_RESULT_MAX_CHARS = 30_000

# Loop breakers: identical (tool, input) invocations allowed before the task
# fails stuck_in_loop, and consecutive failing tool results before a
# change-approach nudge / a tool_failure_loop failure. Hard stops
# (iterations/tokens/timeout/cancel) are unchanged; these only shorten the
# path through futile loops.
DUP_CALL_LIMIT = 5
CONSECUTIVE_FAILURES_NUDGE = 5
CONSECUTIVE_FAILURES_LIMIT = 8


def _cap_tool_result(content: str) -> str:
    """Cap a tool result before it enters history/events (uniform for all tools)."""
    try:
        limit = int(os.environ.get("TOOL_RESULT_MAX_CHARS", DEFAULT_TOOL_RESULT_MAX_CHARS))
    except ValueError:
        limit = DEFAULT_TOOL_RESULT_MAX_CHARS
    if len(content) <= limit:
        return content
    dropped = len(content) - limit
    return content[:limit] + (
        f"\n[... truncated {dropped} chars — output too large; read the file "
        "in slices or narrow the command]"
    )


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
        supports_mcp=True,
        supports_skills=True,
    )
    default_template = DriverTemplate(
        driver="vanilla",
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        available_tools=[
            "read_file", "write_file", "edit_file", "list_files",
            "delete_file", "bash", "python", "web_search", "web_fetch",
            "web_read",
        ],
        tools_user_editable=True,
        supports_context=True,
    )

    def __init__(
        self,
        llm: LLMClient | None = None,
        router: LLMRouter | None = None,
        mcp_factory: Callable[[], Any] | None = None,
    ) -> None:
        if llm is None and router is None:
            raise ValueError("VanillaDriver needs an llm client or a router")
        self._llm = llm
        self._router = router
        self._mcp_factory = mcp_factory

    def _route(self, model: str) -> tuple[LLMClient, str]:
        """(client, wire model id) — router when present, else the fixed client."""
        if self._router is not None:
            return self._router.route(model)
        assert self._llm is not None
        return self._llm, model

    def _make_mcp(self) -> Any:
        if self._mcp_factory is not None:
            return self._mcp_factory()
        from agentcore.mcp_runtime import McpRuntime

        return McpRuntime()

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
        from agentcore.prompt import assemble_system_prompt

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

        # ---- Per-run tool table: built-ins + (skill) — MCP adapters join in
        # Task 5. `done` stays driver-dispatched, never in the table.
        run_tools: dict[str, Tool] = {
            name: TOOLS[name] for name in config.tools if name in TOOLS
        }

        written_skills: list[ShimSkill] = []
        try:
            written = await write_skills(skills_dir(workspace), skills or [])
        except Exception as e:  # noqa: BLE001 — skills must never abort the task
            written = []
            await emit("log", {
                "level": "warn", "message": "skill_materialization_failed",
                "data": {"error": str(e)},
            })
        if skills:
            skipped = [s.name for s in skills if s.name not in written]
            if skipped:
                await emit("log", {
                    "level": "warn", "message": "skills_skipped",
                    "data": {"skills": skipped},
                })
            written_skills = [s for s in skills if s.name in written]
            if written_skills:
                st = SkillTool(
                    base_dir=skills_dir(workspace),
                    names=[s.name for s in written_skills],
                )
                run_tools[st.spec.name] = st

        mcp = None
        if mcp_servers:
            mcp = self._make_mcp()
            try:
                await mcp.connect(mcp_servers)
            except Exception as e:  # noqa: BLE001 — MCP must never abort the task
                await emit("log", {
                    "level": "warn", "message": "mcp_connect_failed",
                    "data": {"error": str(e)},
                })
            for server_name, reason in getattr(mcp, "errors", {}).items():
                await emit("log", {
                    "level": "warn", "message": "mcp_server_unavailable",
                    "data": {"server": server_name, "error": reason},
                })
            for skipped in getattr(mcp, "skipped_tools", []):
                await emit("log", {
                    "level": "warn", "message": "mcp_tool_name_collision",
                    "data": {"tool": skipped},
                })
            for adapter in mcp.tools():
                run_tools[adapter.spec.name] = adapter

        specs: list[ToolSpec] = [t.spec for t in run_tools.values()] + [DONE_TOOL]
        system_prompt = assemble_system_prompt(
            config=config,
            driver_default_system_prompt=DEFAULT_SYSTEM_PROMPT,
            tool_specs=specs,
            task=task,
            limits=limits,
            skills=written_skills or None,
        )
        anthropic_tools = [_tool_spec_to_anthropic(s) for s in specs]
        tool_ctx = ToolContext(workspace=workspace, cancel=cancel, env=env or {})

        call_counts: dict[tuple[str, str], int] = {}
        consecutive_failures = 0
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

        try:
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
                response = await client.create(
                    model=wire_model,
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

                    tool = run_tools.get(tu["name"])
                    if tool is None:
                        msg = f"unknown tool: {tu['name']}"
                        consecutive_failures += 1
                        if consecutive_failures == CONSECUTIVE_FAILURES_NUDGE:
                            msg += (
                                f"\n[{CONSECUTIVE_FAILURES_NUDGE} consecutive tool "
                                "failures — change approach, or call done with "
                                "success=false and a reason]"
                            )
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
                        if consecutive_failures >= CONSECUTIVE_FAILURES_LIMIT:
                            return await _terminal("failed", "tool_failure_loop")
                        continue

                    # Duplicate-call breaker: byte-identical invocations get an
                    # escalating note and, at the limit, stop the task without
                    # executing again.
                    dup_key = (
                        tu["name"],
                        json.dumps(tu["input"], sort_keys=True, default=str),
                    )
                    call_counts[dup_key] = call_counts.get(dup_key, 0) + 1
                    dup_n = call_counts[dup_key]
                    if dup_n >= DUP_CALL_LIMIT:
                        msg = (
                            f"duplicate call limit: this exact {tu['name']} "
                            f"invocation was already made {dup_n - 1} times — "
                            "stopping the task"
                        )
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
                        return await _terminal("failed", "stuck_in_loop")

                    try:
                        res = await tool.run(tu["input"], tool_ctx)
                    except Exception as e:  # noqa: BLE001 — a tool crash must not kill the loop
                        res = ToolResult(
                            ok=False,
                            content=f"tool {tu['name']} crashed: {e}",
                            duration_ms=0,
                        )
                    # Skill content is standing instructions and enforces its
                    # own cap (SKILL_CONTENT_MAX_CHARS) — exempt from the
                    # generic result cap so skills can't be silently gutted.
                    if tu["name"] == "skill":
                        content = res.content
                    else:
                        content = _cap_tool_result(res.content)
                    if dup_n >= 2:
                        content += (
                            f"\n[repeat #{dup_n} of an identical call — if "
                            "nothing changed, change approach]"
                        )
                    if res.ok:
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        if consecutive_failures == CONSECUTIVE_FAILURES_NUDGE:
                            content += (
                                f"\n[{CONSECUTIVE_FAILURES_NUDGE} consecutive tool "
                                "failures — change approach, or call done with "
                                "success=false and a reason]"
                            )
                    await emit(
                        "tool_result",
                        {
                            "tool_use_id": tu["id"],
                            "ok": res.ok,
                            "content": content,
                            "duration_ms": res.duration_ms,
                        },
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": content,
                            "is_error": not res.ok,
                        }
                    )
                    if consecutive_failures >= CONSECUTIVE_FAILURES_LIMIT:
                        return await _terminal("failed", "tool_failure_loop")

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
        finally:
            if mcp is not None:
                try:
                    await mcp.close()
                except Exception:  # noqa: BLE001 — teardown must never mask the result
                    pass


# ---------------------------------------------------------------------------
# Self-register with the real Anthropic client by default.
# The shim injects the configured client; this module-level instance is what
# the registry exposes for capability/template lookup.
# Tests instantiate VanillaDriver directly with a scripted LLM.
# ---------------------------------------------------------------------------

from agentcore.llm.anthropic import AnthropicClient  # noqa: E402

register(VanillaDriver(llm=AnthropicClient(), router=LLMRouter()))
