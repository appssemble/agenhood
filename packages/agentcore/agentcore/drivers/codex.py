"""Codex driver: runs each task on OpenAI's ``codex app-server``.

Near-twin of the opencode driver (spec §3.5.2 best-effort semantics): only
``timeout_seconds`` + cancellation bound it (NOT max_iterations / max_tokens).
Self-registers into DRIVERS via register().

Each task gets its own app-server process, spoken to over JSON-RPC on stdio
(``codex_appserver``):

    codex app-server -c features.plugins=false -c features.apps=false \\
        -c analytics.enabled=false -c otel.exporter=none <tool flags>

then ``thread/start`` (``thread/resume`` for a session continuation) and one
``turn/start`` with the prompt. Notifications are translated back into the
``codex exec --json`` event shape (``codex_events``), so ``codex_event``
payloads look the same to the console and API clients.

- the ``-c`` overrides (``SIDE_CHANNEL_OVERRIDES``) switch off codex's
  ChatGPT-account plugin sync, apps (connectors), analytics and OTEL export.
  codex ran them at startup and shutdown on the task's critical path (0.3-7 s
  measured after the turn) and they added ~2.5k prompt tokens per turn;
- the agent's ``tools`` list switches codex tools (``CODEX_TOOLS``): each is
  emitted on or off explicitly so codex defaults never leak in, except
  ``web_search`` on, which leaves codex's own mode (~2.8k tokens). The
  default is ``web_search`` only; the other tools add ~1k tokens of prompt;
- threads run with ``approvalPolicy: never`` and ``sandbox: danger-full-access``,
  safe because the sandboxed container is itself the security boundary;
- threads are always persisted (``ephemeral: false``). A task without a
  session deletes its thread when its turn ends; structured and session
  threads stay so they can be resumed.

System prompt: sent as the thread's ``developerInstructions``, codex's
"additional developer instructions injected into the session". Measured
2026-09-01 against AGENTS.md and a stdin prefix: same tokens as AGENTS.md,
injected once per session, and the only channel that won a conflict with the
task text. ``remove_stale_agents_md`` clears the AGENTS.md older driver
versions left on persistent volumes.

Auth: ``CODEX_API_KEY`` for the api-key path; for ``oauth_subscription`` the
driver writes ``$CODEX_HOME/auth.json`` instead. CODEX_HOME is redirected under
the writable workspace (the container $HOME is not writable by the running
process, the same constraint opencode solves with XDG).

Hot spare (``codex_spare``): while the container has a free task slot the
driver keeps one more app-server with a thread already started, built from the
last task's settings. A new-thread task with the same settings claims it and
only sends its turn. Each attempt logs ``codex_spare`` with the outcome.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentcore import events, sandbox
from agentcore.drivers.base import (
    DriverCapabilities,
    DriverTemplate,
    EmitFn,
    _coerce_token_pair,
    register,
)
from agentcore.drivers.cli_stream import log_payload
from agentcore.drivers.codex_appserver import (
    AppServerError,
    AppServerReplyError,
    start_app_server,
)
from agentcore.drivers.codex_events import ExecEventTranslator
from agentcore.drivers.codex_spare import SparePool, SpareRecipe, fingerprint
from agentcore.drivers.mcp_config import (
    codex_mcp_env,
    render_codex_mcp_toml,
)
from agentcore.drivers.session_state import read_session_state, write_session_state
from agentcore.drivers.skills_md import write_skills
from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimMcpServer,
    ShimSkill,
    TaskBody,
    TaskResult,
)
from agentcore.structured_output import (
    native_subset_compatible,
    run_structured_attempts,
)
from agentcore.tools.base import ToolSpec


def model_arg(model: str) -> str:
    """The ``-m`` argument codex expects (a bare OpenAI model id).

    Catalog ids for codex are OpenAI models; a fully-qualified ``openai/<id>``
    passes its bare id, anything else passes through unchanged.
    """
    if model.startswith("openai/"):
        return model.split("/", 1)[1]
    return model


def codex_home(workspace: str) -> str:
    """Writable $CODEX_HOME under the agent-owned .agent-state tree."""
    return str(Path(workspace) / ".agent-state" / "codex")


def codex_config_path(workspace: str) -> str:
    """codex's config.toml under the writable CODEX_HOME."""
    return str(Path(codex_home(workspace)) / "config.toml")


def write_codex_config(workspace: str, servers: list[ShimMcpServer]) -> str | None:
    """Write $CODEX_HOME/config.toml with the resolved MCP server blocks.

    Written to a temp file, handed to the agent and renamed into place, so a
    codex process starting at the same moment never sees a half-written,
    missing or root-owned file. Removed when there are no servers, so a
    previous task's servers never linger. Returns None when nothing was written.
    """
    path = Path(codex_config_path(workspace))
    if not servers:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_text(render_codex_mcp_toml(servers))
    os.chmod(tmp, 0o600)
    sandbox.chown_to_agent(str(tmp))
    os.replace(tmp, path)
    return str(path)


WORKSPACE_INSTRUCTION_FILES: tuple[str, ...] = (
    "AGENTS.md", "AGENTS.override.md", ".codex/config.toml",
)


def workspace_instructions_stamp(workspace: str) -> dict[str, str | None]:
    """Content hash of each project file codex reads at ``thread/start``, None if missing."""
    stamp: dict[str, str | None] = {}
    for name in WORKSPACE_INSTRUCTION_FILES:
        try:
            stamp[name] = hashlib.sha256((Path(workspace) / name).read_bytes()).hexdigest()
        except OSError:
            stamp[name] = None
    return stamp


def skills_dir(workspace: str) -> str:
    """Codex's user-global skills discovery dir.

    Codex reads ``$HOME/.agents/skills`` (rust-v0.138.0); the driver redirects
    HOME to ``codex_home``, so skills land at ``<codex_home>/.agents/skills`` —
    inside the hidden, codex-owned runtime dir, never the visible workspace."""
    return str(Path(codex_home(workspace)) / ".agents" / "skills")


def remove_stale_agents_md(workspace: str) -> None:
    """Delete ``$CODEX_HOME/AGENTS.md`` if an older driver left one.

    Until 2026-09 the configured system prompt was materialized there (and
    prefixed on stdin); it now travels as ``developer_instructions``. Workspace
    volumes outlive image upgrades, so without this the old file would double
    the prompt for every pre-existing agent.
    """
    (Path(codex_home(workspace)) / "AGENTS.md").unlink(missing_ok=True)


PROGRESS_INSTRUCTIONS = """\
## Progress updates
The user cannot see your tool calls. Every message you send is a JSON object \
{"progress": ..., "result": ...}.
- Your first message is always a progress update, sent right away before any \
other work, even when you can answer without tools.
- Before each further step (reading files, running commands, searching), send \
another progress update.
- A progress update is \
{"progress": "<one short sentence saying what you are doing>", "result": null}, \
written in the same language as the user's message.
- Send your answer once, as your final message: {"progress": null, "result": <answer>}."""


def developer_instructions(system_prompt: str, *, progress_updates: bool) -> str:
    """The agent's system prompt plus, when enabled, the progress rules."""
    if not progress_updates:
        return system_prompt
    return f"{system_prompt}\n\n{PROGRESS_INSTRUCTIONS}" if system_prompt else PROGRESS_INSTRUCTIONS


def progress_envelope_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Wrap the task's answer shape (``None`` for plain text) so a message is
    either a progress update or the final answer, never both kinds of text."""
    result = {"anyOf": [schema, {"type": "null"}]} if schema else {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["progress", "result"],
        "properties": {"progress": {"type": ["string", "null"]}, "result": result},
    }


def split_envelope(text: str) -> tuple[str | None, Any] | None:
    """``(progress, result)`` from an envelope message, or None for any other text."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"progress", "result"}:
        return None
    progress = value["progress"]
    return (progress if isinstance(progress, str) and progress else None), value["result"]


# codex config overrides applied to every invocation — see the module docstring.
SIDE_CHANNEL_OVERRIDES: tuple[str, ...] = (
    "features.plugins=false",
    "features.apps=false",
    "analytics.enabled=false",
    "otel.exporter=none",
)


@dataclass(frozen=True)
class CodexTool:
    """A codex tool the agent config can switch; ``on``/``off`` are ``-c``
    overrides, None meaning codex's own default applies."""

    name: str
    description: str
    on: str | None
    off: str


CODEX_TOOLS: tuple[CodexTool, ...] = (
    CodexTool("web_search", "Search the web with codex's built-in search.",
              None, "web_search=disabled"),
    CodexTool("image_generation", "Generate images.",
              "features.image_generation=true", "features.image_generation=false"),
    CodexTool("view_image", "Look at image files in the workspace.",
              "features.view_image=true", "features.view_image=false"),
    CodexTool("multi_agent", "Spawn sub-agents that work in parallel.",
              "features.multi_agent=true", "features.multi_agent=false"),
    CodexTool("goals", "Track long-running goals across turns.",
              "features.goals=true", "features.goals=false"),
)
CODEX_DEFAULT_TOOLS: tuple[str, ...] = ("web_search",)


def _side_channel_args() -> list[str]:
    out: list[str] = []
    for override in SIDE_CHANNEL_OVERRIDES:
        out += ["-c", override]
    return out


def tool_args(tools: Iterable[str]) -> list[str]:
    """``-c`` overrides that switch every codex tool on or off."""
    enabled = set(tools)
    out: list[str] = []
    for tool in CODEX_TOOLS:
        override = tool.on if tool.name in enabled else tool.off
        if override is not None:
            out += ["-c", override]
    return out


def build_app_server_command(*, tools: Iterable[str] = CODEX_DEFAULT_TOOLS) -> list[str]:
    """``codex app-server`` with the side-channel and tool overrides.

    Thread and turn settings travel in the JSON-RPC requests instead."""
    return ["codex", "app-server", *_side_channel_args(), *tool_args(tools)]


_THREAD_ACCESS = {"approvalPolicy": "never", "sandbox": "danger-full-access"}


def thread_start_params(*, workspace: str, model: str, instructions: str) -> dict[str, Any]:
    params: dict[str, Any] = {"model": model, "cwd": workspace, "ephemeral": False,
                              **_THREAD_ACCESS}
    if instructions:
        params["developerInstructions"] = instructions
    return params


def thread_resume_params(
    *, thread_id: str, workspace: str, model: str, instructions: str
) -> dict[str, Any]:
    params: dict[str, Any] = {"threadId": thread_id, "model": model, "cwd": workspace,
                              **_THREAD_ACCESS}
    if instructions:
        params["developerInstructions"] = instructions
    return params


def turn_start_params(
    *,
    thread_id: str,
    prompt: str,
    effort: str | None,
    reasoning_summary: bool,
    output_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"threadId": thread_id,
                              "input": [{"type": "text", "text": prompt}]}
    if effort:
        params["effort"] = effort
    if reasoning_summary:
        params["summary"] = "auto"
    if output_schema is not None:
        params["outputSchema"] = output_schema
    return params


def native_output_schema(
    schema: dict[str, Any] | None, *, progress_updates: bool
) -> dict[str, Any] | None:
    """The schema codex enforces for the turn, or None.

    Progress updates wrap the answer in the envelope. A schema outside codex's
    strict subset is left to the shared validate-and-retry loop."""
    if progress_updates:
        schema = progress_envelope_schema(schema)
    if schema is not None and native_subset_compatible(schema):
        return schema
    return None


def build_env(
    base_env: dict[str, str],
    *,
    credential: str,
    credential_kind: str,
    codex_home: str,
) -> dict[str, str]:
    """Redirect CODEX_HOME/HOME to a writable dir; inject CODEX_API_KEY for api-key.

    For ``oauth_subscription`` no env var is set — the driver writes an
    ``auth.json`` under $CODEX_HOME instead.
    """
    env = dict(base_env)
    env["CODEX_HOME"] = codex_home
    env["HOME"] = codex_home
    if credential_kind == "api_key" and credential:
        env["CODEX_API_KEY"] = credential
    return env


def write_auth_json(
    codex_home: str,
    *,
    access_token: str,
    refresh_token: str | None,
    account_id: str | None,
    id_token: str | None,
    last_refresh: str,
) -> str:
    """Write a codex ``auth.json`` (ChatGPT subscription) and return its path.

    Located at ``$CODEX_HOME/auth.json``, mode 0600. ``id_token`` is included
    only when the control plane provides it (test-then-extend, design §9 Risk 1).
    """
    path = Path(codex_home) / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tokens: dict[str, Any] = {"access_token": access_token}
    if id_token:
        tokens["id_token"] = id_token
    if refresh_token:
        tokens["refresh_token"] = refresh_token
    if account_id:
        tokens["account_id"] = account_id
    data: dict[str, Any] = {
        "OPENAI_API_KEY": None,
        "tokens": tokens,
        "last_refresh": last_refresh,
    }
    # Recreate rather than truncate in place: a prior task chowned this file to
    # the agent uid, and the sandbox grants root no CAP_FOWNER, so chmod on a
    # foreign-owned file would EPERM. Unlinking (root has DAC_OVERRIDE on the
    # agent-owned dir) lets the fresh file be root-owned, so chmod succeeds; the
    # caller then chowns it back to the agent.
    path.unlink(missing_ok=True)
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)
    return str(path)


def event_text(event: dict[str, object]) -> str | None:
    """Return the assistant text from an ``item.completed`` agent_message, else None."""
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            return text
    return None


def event_usage(event: dict[str, object]) -> tuple[int, int] | None:
    """Per-turn ``(input, output)`` token counts from a ``turn.completed`` event.

    Maps ``input_tokens``/``output_tokens`` to tokens_in/tokens_out; cached and
    reasoning tokens are dropped (parity with the opencode + vanilla drivers).
    """
    if event.get("type") != "turn.completed":
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    return _coerce_token_pair(usage.get("input_tokens"), usage.get("output_tokens"))


def event_error(event: dict[str, object]) -> str | None:
    """Return an error message from a ``turn.failed`` or ``error`` event, else None."""
    etype = event.get("type")
    if etype == "turn.failed":
        err = event.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg
    if etype == "error":
        msg = event.get("message")
        if isinstance(msg, str):
            return msg
    return None


def event_thread_id(event: dict[str, object]) -> str | None:
    """The codex thread/session id from a ``thread.started`` event, else None."""
    if event.get("type") != "thread.started":
        return None
    tid = event.get("thread_id")
    return tid if isinstance(tid, str) and tid else None


THREAD_REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass
class _TurnState:
    final: Any = None
    error_msg: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


async def _handle_exec_event(
    value: dict[str, Any],
    *,
    state: _TurnState,
    emit: EmitFn,
    progress_updates: bool,
    latest_thread_id: dict[str, str | None],
) -> None:
    """Forward one exec-shaped event and fold it into the turn state."""
    await emit("codex_event", {"raw": value})
    tid = event_thread_id(value)
    if tid:
        latest_thread_id["id"] = tid
    text = event_text(value)
    envelope = split_envelope(text) if text is not None and progress_updates else None
    if envelope is not None:
        progress, answer = envelope
        if progress:
            await emit("progress", events.progress(progress))
        if answer is not None:
            state.final = answer
    elif text is not None:
        state.final = text
    err = event_error(value)
    if err is not None:
        state.error_msg = err
    usage = event_usage(value)
    if usage is not None:
        state.tokens_in += usage[0]
        state.tokens_out += usage[1]
        await emit("token_update", {"tokens_in": state.tokens_in, "tokens_out": state.tokens_out})


_CODEX_PROMPT = (
    "You are an autonomous coding agent (codex). Complete the task in the "
    "workspace and report concisely when finished."
)


async def _start_app_server(cmd: list[str], *, cwd: str, env: dict[str, str]) -> Any:
    return await start_app_server(cmd, cwd=cwd, env=env)


class _SetupStopped(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _within_budget[T](
    step: Coroutine[Any, Any, T], *, cancel: asyncio.Event, deadline: float
) -> T:
    """Await one setup step, raising _SetupStopped if cancel or the deadline comes first.

    A stopped step is cancelled, so the step itself cleans up what it started."""
    if cancel.is_set() or time.monotonic() >= deadline:
        step.close()
        raise _SetupStopped("cancelled" if cancel.is_set() else "timeout")
    task = asyncio.ensure_future(step)
    cancelled = asyncio.ensure_future(cancel.wait())
    try:
        await asyncio.wait({task, cancelled}, timeout=deadline - time.monotonic(),
                           return_when=asyncio.FIRST_COMPLETED)
    finally:
        cancelled.cancel()
        if not task.done():
            task.cancel()
    if not task.done():
        await asyncio.gather(task, return_exceptions=True)
        raise _SetupStopped("cancelled" if cancel.is_set() else "timeout")
    return task.result()


async def _end_early(emit: EmitFn, reason: str) -> TaskResult:
    """Terminal events for a task stopped by cancel (``cancelled``) or its time budget."""
    if reason == "cancelled":
        await emit(
            "status_change",
            {"from": "running", "to": "cancelled", "result": None, "error": None},
        )
        return TaskResult(success=False, reason="cancelled")
    await emit("log", {"level": "warn", "message": "wall-clock timeout", "data": {}})
    await emit(
        "status_change",
        {"from": "running", "to": "timed_out", "result": None,
         "error": {"code": "timeout", "message": "wall-clock timeout"}},
    )
    return TaskResult(success=False, reason="timeout")


class CodexDriver:
    """Driver that shells out to the ``codex`` binary (spec §3.5.3)."""

    name = "codex"
    capabilities = DriverCapabilities(
        supports_tools=False,
        supports_structured_output=True,
        supports_cancel=True,
        requires_image_feature=None,
        supports_mcp=True,
        supports_skills=True,
    )
    default_template = DriverTemplate(
        driver="codex",
        default_system_prompt=_CODEX_PROMPT,
        available_tools=[t.name for t in CODEX_TOOLS],
        tools_user_editable=True,
        supports_context=False,
        default_tools=list(CODEX_DEFAULT_TOOLS),
        tool_specs=[
            ToolSpec(name=t.name, description=t.description, input_schema={})
            for t in CODEX_TOOLS
        ],
    )

    def __init__(self) -> None:
        self._spares = SparePool(_start_app_server)

    def set_capacity_check(self, check: Callable[[], bool]) -> None:
        """The shim's "is there a free task slot" check; spares are only built when it says yes."""
        self._spares.set_capacity_check(check)

    def refill_spare(self) -> None:
        self._spares.refill()

    async def close_spare(self) -> None:
        await self._spares.close()

    async def _start_thread(self, recipe: SpareRecipe) -> tuple[Any, str]:
        client = await start_app_server(recipe.cmd, cwd=recipe.cwd, env=recipe.env)
        try:
            started = await client.request(
                "thread/start", recipe.thread_params, timeout=THREAD_REQUEST_TIMEOUT_SECONDS
            )
            return client, started["thread"]["id"]
        except BaseException:
            client.abort()
            raise

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
        resume_thread_id: str | None = None
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
            resume_thread_id = state.get("thread_id")

        latest_thread_id: dict[str, str | None] = {"id": resume_thread_id}

        schema = (
            task.output.json_schema
            if task.output.type == "structured" and task.output.json_schema is not None
            else None
        )

        if schema is None:
            result = await self._run_codex(
                task=task, config=config, limits=limits, credential=credential,
                emit=emit, cancel=cancel, credential_kind=credential_kind,
                credential_meta=credential_meta, workspace=workspace, skills=skills,
                mcp_servers=mcp_servers, session_id=session_id,
                resume_thread_id=resume_thread_id, latest_thread_id=latest_thread_id,
                env=env, prompt=task.prompt, structured=False, emit_running=True,
                delete_thread=session_id is None,
            )
        else:
            async def attempt(
                prompt: str, resume_id: str | None,
                timeout_seconds: int, emit_running: bool,
            ) -> TaskResult:
                return await self._run_codex(
                    task=task, config=config,
                    limits=limits.model_copy(
                        update={"timeout_seconds": timeout_seconds}
                    ),
                    credential=credential, emit=emit, cancel=cancel,
                    credential_kind=credential_kind,
                    credential_meta=credential_meta, workspace=workspace,
                    skills=skills, mcp_servers=mcp_servers, session_id=session_id,
                    resume_thread_id=resume_id, latest_thread_id=latest_thread_id,
                    env=env, prompt=prompt, structured=True,
                    emit_running=emit_running, delete_thread=False,
                )

            result = await run_structured_attempts(
                schema=schema, task_prompt=task.prompt,
                timeout_seconds=limits.timeout_seconds, emit=emit,
                latest_id=latest_thread_id, run_attempt=attempt,
            )
        if session_id is not None and latest_thread_id["id"]:
            write_session_state(
                workspace, self.name, session_id, {"thread_id": latest_thread_id["id"]}
            )
        return result

    async def _run_codex(
        self,
        *,
        task: TaskBody,
        config: AgentConfig,
        limits: ResolvedLimits,
        credential: str,
        emit: EmitFn,
        cancel: asyncio.Event,
        credential_kind: str,
        credential_meta: dict[str, Any] | None,
        workspace: str,
        skills: list[ShimSkill] | None,
        mcp_servers: list[ShimMcpServer] | None,
        session_id: str | None,
        resume_thread_id: str | None,
        latest_thread_id: dict[str, str | None],
        env: dict[str, str] | None = None,
        prompt: str,
        structured: bool = False,
        emit_running: bool = True,
        delete_thread: bool = False,
    ) -> TaskResult:
        start = time.monotonic()
        Path(workspace).mkdir(parents=True, exist_ok=True)

        if emit_running:
            await emit(
                "status_change",
                {"from": "pending", "to": "running", "result": None, "error": None},
            )

        home = codex_home(workspace)
        sandbox.ensure_agent_dir(home)
        output_schema = native_output_schema(
            task.output.json_schema if structured else None,
            progress_updates=config.progress_updates,
        )
        child_env = build_env(
            sandbox.build_child_env(env),
            credential=credential,
            credential_kind=credential_kind,
            codex_home=home,
        )

        # Older drivers wrote the system prompt to AGENTS.md; clear any
        # survivor so it cannot double the developer_instructions below.
        try:
            remove_stale_agents_md(workspace)
        except Exception as exc:  # noqa: BLE001 — cleanup is best-effort
            await emit("log", {"level": "warn", "message": "system_prompt_error",
                               "data": {"error": str(exc)}})

        # Materialize codex skills into the discovery dir (best-effort: a
        # failure must never change the task outcome — skills are an enhancement).
        # makedirs_agent, not ensure_agent_dir: `.agents` is a brand-new
        # intermediate the first time this runs, and ensure_agent_dir only
        # chowns the leaf it's given, leaving `.agents` root-owned and unwritable
        # by the dropped agent user (same bug class as claude_code.py).
        try:
            sandbox.makedirs_agent(skills_dir(workspace))
            names = await write_skills(skills_dir(workspace), skills or [])
            if names:
                await emit(
                    "log",
                    log_payload(
                        "skills_materialized",
                        data={"count": len(names), "names": names},
                    ),
                )
        except Exception as exc:  # noqa: BLE001 — skills are best-effort
            await emit(
                "log",
                log_payload(
                    "skills_error",
                    level="warn",
                    message=str(exc),
                    data={"error": str(exc)},
                ),
            )

        # Subscription auth: write auth.json from the control-plane-refreshed token.
        if credential_kind == "oauth_subscription" and credential:
            meta = credential_meta or {}
            auth_path = write_auth_json(
                home,
                access_token=credential,
                refresh_token=meta.get("refresh_token"),
                account_id=meta.get("account_id"),
                id_token=meta.get("id_token"),
                last_refresh=datetime.now(UTC).isoformat(),
            )
            sandbox.chown_to_agent(auth_path)

        # config.toml: MCP servers (best-effort, surfaced as a warn). MCP secrets
        # ride env vars codex reads at startup.
        try:
            write_codex_config(workspace, mcp_servers or [])
            if mcp_servers:
                child_env.update(codex_mcp_env(mcp_servers))
                await emit(
                    "log", log_payload("mcp_materialized", data={"count": len(mcp_servers)})
                )
        except Exception as exc:  # noqa: BLE001 - config is best-effort
            await emit(
                "log",
                log_payload("mcp_error", level="warn", message=str(exc),
                            data={"error": str(exc)}),
            )

        model = model_arg(config.model)
        instructions = developer_instructions(
            config.system_prompt or "", progress_updates=config.progress_updates
        )
        cmd = build_app_server_command(tools=config.tools)
        start_params = thread_start_params(workspace=workspace, model=model,
                                           instructions=instructions)
        recipe = SpareRecipe(
            cmd=cmd, cwd=workspace, env=child_env, thread_params=start_params,
            fingerprint=fingerprint(
                cmd, workspace, child_env, start_params, credential_kind, credential,
                credential_meta or {}, [s.model_dump() for s in skills or []],
                [m.model_dump() for m in mcp_servers or []],
                workspace_instructions_stamp(workspace),
            ),
        )
        self._spares.remember(recipe if config.hot_spare else None)

        def turn_params(tid: str) -> dict[str, Any]:
            return turn_start_params(thread_id=tid, prompt=prompt, effort=config.effort,
                                     reasoning_summary=config.reasoning_summary,
                                     output_schema=output_schema)

        async def note_spare(outcome: str, reason: str | None = None) -> None:
            data = {"outcome": outcome} if reason is None else {"outcome": outcome,
                                                                "reason": reason}
            await emit("log", log_payload("codex_spare", data=data))

        def bounded[T](step: Coroutine[Any, Any, T]) -> Coroutine[Any, Any, T]:
            return _within_budget(step, cancel=cancel,
                                  deadline=start + limits.timeout_seconds)

        async def thread_started(tid: str) -> None:
            await _handle_exec_event(
                translator.thread_started(tid), state=state, emit=emit,
                progress_updates=config.progress_updates, latest_thread_id=latest_thread_id,
            )

        translator = ExecEventTranslator()
        state = _TurnState()
        client: Any = None
        try:
            if resume_thread_id:
                await note_spare("miss", "resume")
                client = await bounded(start_app_server(cmd, cwd=workspace, env=child_env))
                await bounded(client.request(
                    "thread/resume",
                    thread_resume_params(thread_id=resume_thread_id, workspace=workspace,
                                         model=model, instructions=instructions),
                    timeout=THREAD_REQUEST_TIMEOUT_SECONDS,
                ))
                thread_id = resume_thread_id
                await thread_started(thread_id)
                await bounded(client.request("turn/start", turn_params(thread_id),
                                             timeout=THREAD_REQUEST_TIMEOUT_SECONDS))
            else:
                if config.hot_spare:
                    spare, reason = await bounded(self._spares.claim(recipe.fingerprint))
                else:
                    spare, reason = None, "disabled"
                if spare is not None:
                    client, thread_id = spare.client, spare.thread_id
                    await note_spare("hit")
                else:
                    await note_spare("miss", reason)
                    client, thread_id = await bounded(self._start_thread(recipe))
                await thread_started(thread_id)
                try:
                    await bounded(client.request("turn/start", turn_params(thread_id),
                                                 timeout=THREAD_REQUEST_TIMEOUT_SECONDS))
                except AppServerError as exc:
                    if spare is None or isinstance(exc, AppServerReplyError):
                        raise
                    # The spare died after warming: start this attempt cold, once.
                    client.abort()
                    client = None
                    await note_spare("miss", "dead")
                    client, thread_id = await bounded(self._start_thread(recipe))
                    await thread_started(thread_id)
                    await bounded(client.request("turn/start", turn_params(thread_id),
                                                 timeout=THREAD_REQUEST_TIMEOUT_SECONDS))
                self._spares.refill()
        except _SetupStopped as stopped:
            if client is not None:
                client.abort()
            return await _end_early(emit, stopped.reason)
        except FileNotFoundError:
            await emit(
                "status_change",
                {"from": "running", "to": "failed", "result": None,
                 "error": {"code": "codex_unavailable", "message": "codex binary not found"}},
            )
            return TaskResult(success=False, reason="codex_unavailable")
        except (AppServerError, KeyError, TypeError) as exc:
            if client is not None:
                await client.close(timeout=1.0)
            await emit(
                "status_change",
                {"from": "running", "to": "failed", "result": None,
                 "error": {"code": "codex_error", "message": str(exc)}},
            )
            return TaskResult(success=False, reason="codex_error")
        except BaseException:
            if client is not None:
                client.abort()
            raise

        return await self._drive_turn(
            client, thread_id=thread_id, translator=translator, state=state, emit=emit,
            cancel=cancel, start=start, limits=limits, progress_updates=config.progress_updates,
            latest_thread_id=latest_thread_id, structured=structured,
            delete_thread=delete_thread,
        )

    async def _drive_turn(
        self,
        client: Any,
        *,
        thread_id: str,
        translator: ExecEventTranslator,
        state: _TurnState,
        emit: EmitFn,
        cancel: asyncio.Event,
        start: float,
        limits: ResolvedLimits,
        progress_updates: bool,
        latest_thread_id: dict[str, str | None],
        structured: bool,
        delete_thread: bool,
    ) -> TaskResult:
        """Stream one started turn to its end and map the outcome to a TaskResult.

        ``start`` is when the attempt began; its time budget counts from there."""
        status: str | None = None
        returncode: int | None = None
        try:
            while True:
                if cancel.is_set():
                    client.terminate()
                    return await _end_early(emit, "cancelled")
                if time.monotonic() - start >= limits.timeout_seconds:
                    client.terminate()
                    return await _end_early(emit, "timeout")

                message = await client.next_message(timeout=1.0)
                if message is None:
                    continue
                method = message.get("method")
                params = message.get("params") or {}
                if method == "_stderr":
                    await emit("codex_stdout", {"line": params.get("line", "")})
                    continue
                if method == "_declined":
                    await emit("log", log_payload(
                        "codex_client_request_declined", level="warn",
                        data={"request": params.get("request")}))
                    continue
                if method == "_exit":
                    returncode = params.get("returncode")
                    break
                for value in translator.translate(message):
                    await _handle_exec_event(
                        value, state=state, emit=emit, progress_updates=progress_updates,
                        latest_thread_id=latest_thread_id,
                    )
                if method == "turn/completed":
                    status = (params.get("turn") or {}).get("status")
                    break

            if delete_thread and status is not None:
                try:
                    await client.request("thread/delete", {"threadId": thread_id}, timeout=5.0)
                except AppServerError:
                    pass
        except Exception as exc:  # noqa: BLE001 - surface any stream failure as codex_error
            client.terminate()
            await emit(
                "status_change",
                {"from": "running", "to": "failed", "result": None,
                 "error": {"code": "codex_error", "message": str(exc)}},
            )
            return TaskResult(success=False, reason="codex_error")
        finally:
            await client.close()

        if status == "completed":
            output = state.final if state.final is not None else ""
            if structured:
                return TaskResult(success=True, output=output)
            await emit(
                "status_change",
                {"from": "running", "to": "completed",
                 "result": {"success": True, "output": output}, "error": None},
            )
            return TaskResult(success=True, output=output)

        if status is not None:
            message_text = state.error_msg or f"codex turn {status}"
            code = "codex_error"
        else:
            message_text = state.error_msg or f"codex exited {returncode}"
            code = "codex_error" if state.error_msg else "codex_nonzero_exit"
        await emit(
            "status_change",
            {"from": "running", "to": "failed", "result": None,
             "error": {"code": code, "message": message_text}},
        )
        return TaskResult(success=False, reason=message_text)


register(CodexDriver())
