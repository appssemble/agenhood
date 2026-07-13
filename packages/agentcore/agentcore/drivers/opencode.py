"""Opencode driver — shells out to the ``opencode`` binary (opencode-ai >= 1.x).

Spec §3.5.2 (best-effort in v1): only ``timeout_seconds`` + cancellation bound
this driver (NOT max_iterations / max_tokens). It runs ``opencode run`` with
``--format json``, forwards the structured JSON events, and extracts the
assistant's final text as the result. Self-registers into DRIVERS via register().

opencode 1.x CLI (verified against opencode-ai@1.15.13 — the 0.x flags
``--workspace`` / ``--prompt-file`` / ``--json-events`` were removed):

    opencode run --dir <ws> --format json -m <provider>/<model> \\
        --dangerously-skip-permissions -- "<prompt>"

- the prompt is a **positional** message; the ``--`` guard lets a prompt start
  with ``-`` without being parsed as a flag;
- ``--dir`` sets the working directory (was ``--workspace``);
- ``--format json`` emits one JSON event object per line (was ``--json-events``);
- ``-m provider/model`` selects the model (opencode resolves it via models.dev);
- ``--dangerously-skip-permissions`` auto-approves tool use — safe here because
  the sandboxed container is itself the security boundary.

opencode reads the provider key from the env var the provider expects
(``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``); no ``auth.json`` is needed for the
API-key path.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from agentcore import sandbox
from agentcore.drivers.base import (
    DriverCapabilities,
    DriverTemplate,
    EmitFn,
    _coerce_token_pair,
    register,
)
from agentcore.drivers.cli_stream import classify_json_line, log_payload
from agentcore.drivers.mcp_config import render_opencode_mcp
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

_OPENCODE_PROMPT = (
    "You are an autonomous coding agent (opencode). Complete the task in the "
    "workspace and report concisely when finished."
)

# Provider key env var opencode reads natively, per provider id. Both opencode
# (Zen) and opencode-go (Go plan) read the same OPENCODE_API_KEY.
_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "opencode": "OPENCODE_API_KEY",
    "opencode-go": "OPENCODE_API_KEY",
}


def provider_for_model(model: str) -> str:
    """Map a model id to the opencode provider id used in ``-m provider/model``.

    A fully-qualified ``provider/model`` id (``opencode/...``, ``anthropic/...``)
    takes its provider from the prefix. A bare id mirrors the control plane's
    routing: GPT / o-series → ``openai``; everything else → ``anthropic``.
    """
    if "/" in model:
        return model.split("/", 1)[0].lower()
    m = model.lower()
    if m.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    return "anthropic"


def model_ref(model: str) -> str:
    """The ``-m`` argument opencode expects (``provider/model``).

    Already-qualified ids (``opencode/deepseek-v4-flash-free``) pass through;
    bare ids are prefixed with the resolved provider.
    """
    if "/" in model:
        return model
    return f"{provider_for_model(model)}/{model}"


def parse_opencode_line(line: str) -> tuple[str, object | None]:
    """Classify one line of opencode output.

    Returns:
        ('event', dict) for JSON-structured event lines,
        ('stdout', str)  for plain text lines,
        ('ignore', None) for blank/whitespace-only lines.
    """
    return classify_json_line(line)


def event_text(event: dict[str, object]) -> str | None:
    """Return the assistant text from a ``type:"text"`` event, else None.

    opencode --format json emits ``{"type":"text","part":{"text": "...", ...}}``
    for assistant output. The latest such text is the task's result.
    """
    if event.get("type") != "text":
        return None
    part = event.get("part")
    if isinstance(part, dict):
        text = part.get("text")
        if isinstance(text, str):
            return text
    return None


def event_error(event: dict[str, object]) -> str | None:
    """Return an error message from a ``type:"error"`` event, else None.

    Shape: ``{"type":"error","error":{"name":...,"data":{"message":...}}}``.
    """
    if event.get("type") != "error":
        return None
    err = event.get("error")
    if isinstance(err, dict):
        data = err.get("data")
        if isinstance(data, dict):
            message = data.get("message")
            if isinstance(message, str):
                return message
        name = err.get("name")
        if isinstance(name, str):
            return name
    return None


def event_tokens(event: dict[str, object]) -> tuple[int, int] | None:
    """Per-step ``(input, output)`` token counts from a ``step_finish`` event, else None.

    opencode (opencode-ai 1.x) in ``--format json`` emits, per completed model
    step, ``{"type":"step_finish", ..., "part":{"type":"step-finish","tokens":
    {"input":N,"output":N,"reasoning":N,"cache":{"read":N,"write":N}}}}``.
    ``part.tokens`` is the usage for THAT step (AI-SDK ``finish-step`` semantics);
    the cumulative total is NOT re-emitted in json mode, so the caller accumulates
    across steps (see ``OpencodeDriver.run``) to match the vanilla driver's
    cumulative ``token_update`` contract.

    ``input``/``output`` map to ``tokens_in``/``tokens_out`` exactly as the
    Anthropic adapter does for the vanilla driver (``llm/anthropic.py``); cache
    and reasoning are intentionally left out so both drivers report the same way.
    """
    if event.get("type") != "step_finish":
        return None
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    tokens = part.get("tokens")
    if not isinstance(tokens, dict):
        return None
    return _coerce_token_pair(tokens.get("input"), tokens.get("output"))


def event_session_id(event: dict[str, object]) -> str | None:
    """opencode's own session id, else None.

    Verified against opencode's documented ``run --format json`` schema: every
    event type (text, tool_use, step_start, step_finish, error) carries a
    top-level ``sessionID`` field in the form ``ses_XXXXXXXXXXXXXXXXXXXX``.
    """
    sid = event.get("sessionID")
    return sid if isinstance(sid, str) and sid else None


def build_command(
    *, workspace: str, model_ref: str, prompt: str, resume_session_id: str | None = None
) -> list[str]:
    """Build the opencode 1.x CLI invocation (verified against opencode-ai@1.15.13)."""
    cmd = [
        "opencode",
        "run",
        "--dir",
        workspace,
        "--format",
        "json",
        "-m",
        model_ref,
        "--dangerously-skip-permissions",
    ]
    if resume_session_id:
        cmd += ["-s", resume_session_id]
    cmd += ["--", prompt]
    return cmd


def build_env(
    base_env: dict[str, str],
    *,
    provider: str,
    credential: str,
    credential_kind: str = "api_key",
) -> dict[str, str]:
    """Inject the provider's API-key env var (opencode reads it natively).

    For ``oauth_subscription`` no env var is set — the driver writes an
    ``auth.json`` instead (the ``type:"oauth"`` entry is what routes opencode to
    the Codex backend). Keyless providers pass an empty credential.
    """
    env = dict(base_env)
    if credential_kind != "api_key":
        return env
    var = _PROVIDER_ENV.get(provider)
    if var and credential:
        env[var] = credential
    return env


def write_auth_json(
    workspace: str,
    *,
    access_token: str,
    refresh_token: str | None,
    account_id: str | None,
    expires_ms: int,
) -> str:
    """Write an opencode auth.json (oauth) and return its path.

    Located at ``$XDG_DATA_HOME/opencode/auth.json`` for the driver's XDG layout
    (``workspace_xdg``). Mode 0600. The ``refresh`` token is included because
    opencode's Codex loader requires it to register the credential and load the
    ChatGPT subscription model catalog (spec §13; Approach B). opencode self-
    refreshes only when the access token has expired — the control plane keeps the
    injected access token fresh, so for normal-length tasks opencode does not.
    """
    data_home = workspace_xdg(workspace)["XDG_DATA_HOME"]
    auth_dir = Path(data_home) / "opencode"
    auth_dir.mkdir(parents=True, exist_ok=True)
    path = auth_dir / "auth.json"
    entry: dict[str, object] = {"type": "oauth", "access": access_token, "expires": expires_ms}
    if refresh_token:
        entry["refresh"] = refresh_token
    if account_id:
        entry["accountId"] = account_id
    # Recreate rather than truncate in place: a prior task chowned this file to
    # the agent uid, and the sandbox grants root no CAP_FOWNER, so chmod on a
    # foreign-owned file would EPERM. Unlinking (root has DAC_OVERRIDE on the
    # agent-owned dir) lets the fresh file be root-owned, so chmod succeeds; the
    # caller then chowns it back to the agent.
    path.unlink(missing_ok=True)
    path.write_text(json.dumps({"openai": entry}))
    os.chmod(path, 0o600)
    return str(path)


def workspace_xdg(workspace: str) -> dict[str, str]:
    """XDG base dirs under the (writable) workspace.

    opencode writes its sqlite db / config / cache under ``$XDG_DATA_HOME`` etc.
    The provisioned agent container's ``$HOME`` (``/home/agent``) is not writable
    by the running process, so opencode's default ``~/.local/share`` mkdir fails
    with EACCES. Redirect the XDG dirs into ``/workspace/.agent-state`` — the
    agent-owned runtime tree created by the shim.
    """
    base = Path(workspace) / ".agent-state" / "opencode"
    return {
        "XDG_DATA_HOME": str(base / "data"),
        "XDG_CONFIG_HOME": str(base / "config"),
        "XDG_CACHE_HOME": str(base / "cache"),
        "HOME": str(base),
    }


def opencode_log_path(workspace: str) -> str:
    """Path to opencode's own structured log under the driver's XDG layout.

    opencode writes ``$XDG_DATA_HOME/opencode/log/opencode.log``. This is the
    ONLY place opencode reports a model-stream failure (e.g. a free-plan rate
    limit): in ``run --format json`` mode such a failure is written here but NOT
    emitted on stdout, and the ``opencode run`` process neither exits nor closes
    stdout — it hangs. The driver tails this file to detect that and fail fast
    instead of waiting out the whole wall-clock timeout.
    """
    data_home = workspace_xdg(workspace)["XDG_DATA_HOME"]
    return str(Path(data_home) / "opencode" / "log" / "opencode.log")


def scan_opencode_log_for_fatal(text: str) -> str | None:
    """Return a terminal-failure reason if ``text`` (freshly-appended opencode
    log lines) shows an unrecoverable model-stream failure, else None.

    Detects the free-plan / provider rate-limit hang: opencode logs a
    ``level=ERROR message="stream error" ... error.error="...Rate limit
    exceeded..."`` line and then stalls without exiting or emitting stdout.
    Matching only freshly-appended text (the caller tracks a byte offset) keeps
    a stale error from a previous task in the same container from mis-firing.
    """
    for line in text.splitlines():
        if 'message="stream error"' in line and "Rate limit exceeded" in line:
            return "rate_limited"
    return None


def _read_appended_log(path: str, offset: int) -> tuple[str, int]:
    """Read the bytes appended to ``path`` since ``offset``; return (text, new
    offset). Missing/unreadable file → ("", offset). Byte offsets keep this
    correct even when the log holds partial multi-byte writes."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
        return data.decode("utf-8", "replace"), offset + len(data)
    except OSError:
        return "", offset


def skills_dir(workspace: str) -> str:
    """opencode's global skills discovery dir under the driver's XDG layout."""
    cfg = workspace_xdg(workspace)["XDG_CONFIG_HOME"]
    return str(Path(cfg) / "opencode" / "skills")


def opencode_config_path(workspace: str) -> str:
    """opencode's global config file under the driver's XDG layout."""
    cfg = workspace_xdg(workspace)["XDG_CONFIG_HOME"]
    return str(Path(cfg) / "opencode" / "opencode.json")


def write_opencode_mcp(workspace: str, servers: list[ShimMcpServer]) -> int:
    """Rewrite the ``mcp`` block in opencode.json. Returns count written.

    When ``servers`` is empty, clears any prior ``mcp`` block and returns 0.
    If there are no servers and no existing file / ``mcp`` key, does nothing
    (no file is created).  Non-``mcp`` top-level keys are always preserved.
    Unlike the old merge behaviour, each call is a full replace so deselected
    servers' inline Authorization-header secrets do not linger across tasks."""
    path = Path(opencode_config_path(workspace))
    existing: dict[str, Any] = {}
    file_exists = path.exists()
    if file_exists:
        try:
            existing = json.loads(path.read_text())
        except (ValueError, OSError):
            existing = {}
    # Nothing to write AND nothing to clear — bail without touching the fs.
    if not servers and (not file_exists or "mcp" not in existing):
        return 0
    mcp_block: dict[str, Any] = render_opencode_mcp(servers)["mcp"] if servers else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    existing["mcp"] = mcp_block
    path.write_text(json.dumps(existing))
    os.chmod(path, 0o600)
    return len(mcp_block)


async def materialize_skills(
    workspace: str, skills: list[ShimSkill]
) -> list[str]:
    """opencode materialization — delegates to the shared writer using
    opencode's discovery dir. Kept as a named wrapper for the existing call
    site and tests."""
    return await write_skills(skills_dir(workspace), skills)


class OpencodeDriver:
    """Driver that shells out to the ``opencode`` binary (spec §3.5.2)."""

    name = "opencode"
    capabilities = DriverCapabilities(
        supports_tools=False,
        supports_structured_output=False,
        supports_cancel=True,
        requires_image_feature=None,
        supports_mcp=True,
    )
    default_template = DriverTemplate(
        driver="opencode",
        default_system_prompt=_OPENCODE_PROMPT,
        available_tools=[],  # opencode owns its tools; list is empty
        tools_user_editable=False,
        supports_context=False,
    )

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
    ) -> TaskResult:
        resume_session_id: str | None = None
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
            resume_session_id = state.get("opencode_session_id")

        latest_session_id: dict[str, str | None] = {"id": resume_session_id}
        result = await self._run_opencode(
            task=task, config=config, limits=limits, credential=credential, emit=emit,
            cancel=cancel, credential_kind=credential_kind, credential_meta=credential_meta,
            workspace=workspace, skills=skills, mcp_servers=mcp_servers,
            resume_session_id=resume_session_id, latest_session_id=latest_session_id,
        )
        if session_id is not None and latest_session_id["id"]:
            write_session_state(
                workspace, self.name, session_id,
                {"opencode_session_id": latest_session_id["id"]},
            )
        return result

    async def _run_opencode(
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
        resume_session_id: str | None,
        latest_session_id: dict[str, str | None],
    ) -> TaskResult:
        Path(workspace).mkdir(parents=True, exist_ok=True)

        await emit(
            "status_change",
            {"from": "pending", "to": "running", "result": None, "error": None},
        )

        provider = provider_for_model(config.model)
        cmd = build_command(
            workspace=workspace, model_ref=model_ref(config.model), prompt=task.prompt,
            resume_session_id=resume_session_id,
        )
        env = build_env(
            sandbox.build_child_env(),
            provider=provider,
            credential=credential,
            credential_kind=credential_kind,
        )
        # opencode needs writable data/config dirs owned by the agent uid; the
        # container's $HOME is not writable, so point XDG at .agent-state.
        xdg = workspace_xdg(workspace)
        for path in xdg.values():
            sandbox.ensure_agent_dir(path)
        env.update(xdg)

        # Materialize opencode skills into the discovery dir (best-effort: a
        # failure must never change the task outcome — skills are an enhancement).
        # makedirs_agent, not ensure_agent_dir: `config/opencode` is a brand-new
        # intermediate the first time this runs, and ensure_agent_dir only chowns
        # the leaf it's given, leaving it root-owned and unwritable by the
        # dropped agent user (same bug class as claude_code.py).
        try:
            sandbox.makedirs_agent(skills_dir(workspace))
            names = await materialize_skills(workspace, skills or [])
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

        # Materialize MCP servers into opencode.json (best-effort, like skills).
        try:
            count = write_opencode_mcp(workspace, mcp_servers or [])
            # Chown whenever the config file exists (covers both the write and
            # the clear paths) so the agent process can read/update it.
            if os.path.exists(opencode_config_path(workspace)):
                sandbox.chown_to_agent(opencode_config_path(workspace))
            if count:
                await emit("log", log_payload("mcp_materialized", data={"count": count}))
        except Exception as exc:  # noqa: BLE001 — MCP is best-effort
            await emit(
                "log",
                log_payload(
                    "mcp_error",
                    level="warn",
                    message=str(exc),
                    data={"error": str(exc)},
                ),
            )

        # Subscription auth: write auth.json with the (control-plane-refreshed)
        # access token + refresh token so opencode's Codex loader registers the
        # credential and loads the ChatGPT model catalog (spec §13; Approach B).
        if credential_kind == "oauth_subscription" and credential:
            meta = credential_meta or {}
            auth_path = write_auth_json(
                workspace,
                access_token=credential,
                refresh_token=meta.get("refresh_token"),
                account_id=meta.get("account_id"),
                expires_ms=int(meta.get("expires_ms", 0)),
            )
            # The nested opencode/ data dir is created by write_auth_json via a
            # plain mkdir (root-owned when the shim is root); chown both it and
            # the auth.json so the dropped agent process can write its db there.
            sandbox.ensure_agent_dir(os.path.dirname(auth_path))
            sandbox.chown_to_agent(auth_path)

        try:
            proc = await sandbox.spawn_untrusted(
                cmd,
                cwd=workspace,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            # opencode binary missing → best-effort: emit a single failure event.
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {
                        "code": "opencode_unavailable",
                        "message": "opencode binary not found",
                    },
                },
            )
            return TaskResult(success=False, reason="opencode_unavailable")

        start = time.monotonic()
        last_text: str | None = None  # most-recent assistant text → the result
        error_msg: str | None = None  # last error event message (enriches failures)
        tokens_in = 0  # cumulative across step_finish events (parity w/ vanilla)
        tokens_out = 0
        # opencode reports a fatal model-stream failure (e.g. a free-plan rate
        # limit) ONLY in its log file, then hangs without exiting or emitting
        # stdout. Tail the log from its current end so we can fail fast; scanning
        # only newly-appended bytes ignores a stale error from a prior task.
        log_path = opencode_log_path(workspace)
        try:
            log_offset = os.path.getsize(log_path)
        except OSError:
            log_offset = 0
        try:
            assert proc.stdout is not None
            while True:
                if cancel.is_set():
                    sandbox.terminate(proc)
                    await emit(
                        "status_change",
                        {
                            "from": "running",
                            "to": "cancelled",
                            "result": None,
                            "error": None,
                        },
                    )
                    return TaskResult(success=False, reason="cancelled")

                if time.monotonic() - start >= limits.timeout_seconds:
                    sandbox.terminate(proc)
                    await emit(
                        "log",
                        {"level": "warn", "message": "wall-clock timeout", "data": {}},
                    )
                    await emit(
                        "status_change",
                        {
                            "from": "running",
                            "to": "timed_out",
                            "result": None,
                            "error": {
                                "code": "timeout",
                                "message": "wall-clock timeout",
                            },
                        },
                    )
                    return TaskResult(success=False, reason="timeout")

                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except TimeoutError:
                    if proc.returncode is not None:
                        break
                    # stdout idle for 1s — the moment a rate-limit hang shows up.
                    # Check opencode's log for a fatal stream error and bail fast.
                    appended, log_offset = _read_appended_log(log_path, log_offset)
                    fatal = scan_opencode_log_for_fatal(appended) if appended else None
                    if fatal:
                        sandbox.terminate(proc)
                        await emit(
                            "status_change",
                            {
                                "from": "running",
                                "to": "failed",
                                "result": None,
                                "error": {
                                    "code": fatal,
                                    "message": (
                                        "opencode model stream failed: rate limit "
                                        "exceeded (free-plan limit reached?)"
                                    ),
                                },
                            },
                        )
                        return TaskResult(success=False, reason=fatal)
                    continue

                if not raw:
                    break

                line = raw.decode("utf-8", "replace").rstrip("\n")
                kind, value = parse_opencode_line(line)
                if kind == "event":
                    assert isinstance(value, dict)
                    await emit("opencode_event", {"raw": value})
                    sid = event_session_id(value)
                    if sid:
                        latest_session_id["id"] = sid
                    text = event_text(value)
                    if text is not None:
                        last_text = text
                    err = event_error(value)
                    if err is not None:
                        error_msg = err
                    usage = event_tokens(value)
                    if usage is not None:
                        # opencode reports per-step usage; accumulate and emit the
                        # running total so token_update carries the cumulative
                        # count (the shim + control plane overwrite with the
                        # latest value — same contract as the vanilla driver).
                        tokens_in += usage[0]
                        tokens_out += usage[1]
                        await emit(
                            "token_update",
                            {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        )
                elif kind == "stdout":
                    assert isinstance(value, str)
                    await emit("opencode_stdout", {"line": value})

            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception as exc:  # pragma: no cover — defensive
            sandbox.terminate(proc)
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {"code": "opencode_error", "message": str(exc)},
                },
            )
            return TaskResult(success=False, reason="opencode_error")

        if rc == 0:
            result = {"success": True, "output": last_text or ""}
            await emit(
                "status_change",
                {"from": "running", "to": "completed", "result": result, "error": None},
            )
            return TaskResult(success=True, output=last_text or "")

        # Non-zero exit → failed; prefer the captured error-event message.
        message = error_msg or f"opencode exited {rc}"
        await emit(
            "status_change",
            {
                "from": "running",
                "to": "failed",
                "result": None,
                "error": {
                    "code": "opencode_error" if error_msg else "opencode_nonzero_exit",
                    "message": message,
                },
            },
        )
        return TaskResult(success=False, reason=message)


register(OpencodeDriver())
