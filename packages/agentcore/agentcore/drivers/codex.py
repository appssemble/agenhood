"""Codex driver — shells out to OpenAI's ``codex`` CLI (``codex exec``).

Near-twin of the opencode driver (spec §3.5.2 best-effort semantics): only
``timeout_seconds`` + cancellation bound it (NOT max_iterations / max_tokens).
Runs ``codex exec --json`` with the prompt on stdin, forwards the JSONL events,
and extracts the final ``agent_message`` text as the result. Self-registers into
DRIVERS via register().

codex exec CLI (OpenAI codex):

    codex exec --json --skip-git-repo-check --ephemeral \\
        -C <ws> -m <model> --dangerously-bypass-approvals-and-sandbox -

- ``--json`` emits one JSON event object per line on stdout;
- the trailing ``-`` reads the prompt from stdin (robust vs prompts starting "-");
- ``--dangerously-bypass-approvals-and-sandbox`` auto-approves + full access —
  safe because the sandboxed container is itself the security boundary;
- ``--ephemeral`` keeps session rollout files off disk; ``--skip-git-repo-check``
  because workspaces are not git repos;
- ``-C`` sets the working dir; ``-m`` selects the (bare OpenAI) model.

Auth: ``CODEX_API_KEY`` for the api-key path (codex exec ignores OPENAI_API_KEY);
for ``oauth_subscription`` the driver writes ``$CODEX_HOME/auth.json`` instead.
CODEX_HOME is redirected under the writable workspace (the container $HOME is not
writable by the running process — same constraint opencode solves with XDG).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
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
from agentcore.drivers.mcp_config import codex_mcp_env, render_codex_mcp_toml
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


def write_codex_mcp(workspace: str, servers: list[ShimMcpServer]) -> int:
    """Write the resolved MCP servers into $CODEX_HOME/config.toml. Returns count.
    No-op when there are no servers. This file is exclusively MCP config (codex's
    only other state file is auth.json), so it is written fresh each task."""
    if not servers:
        return 0
    path = Path(codex_config_path(workspace))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)  # prior task may have chowned it to the agent uid
    path.write_text(render_codex_mcp_toml(servers))
    os.chmod(path, 0o600)
    return len(servers)


def skills_dir(workspace: str) -> str:
    """Codex's user-global skills discovery dir.

    Codex reads ``$HOME/.agents/skills`` (rust-v0.138.0); the driver redirects
    HOME to ``codex_home``, so skills land at ``<codex_home>/.agents/skills`` —
    inside the hidden, codex-owned runtime dir, never the visible workspace."""
    return str(Path(codex_home(workspace)) / ".agents" / "skills")


def build_command(*, workspace: str, model: str, ephemeral: bool = True) -> list[str]:
    """Build the ``codex exec`` invocation (prompt is fed on stdin via ``-``).

    ``ephemeral=False`` drops ``--ephemeral`` so the rollout file persists,
    used for the first turn of a session (driver-sessions spec §4).
    """
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check"]
    if ephemeral:
        cmd.append("--ephemeral")
    cmd += [
        "-C", workspace, "-m", model,
        "--dangerously-bypass-approvals-and-sandbox", "-",
    ]
    return cmd


def build_resume_command(*, model: str, thread_id: str) -> list[str]:
    """Build ``codex exec resume`` (continuing a prior session).

    Verified live against the installed codex CLI: the ``resume`` subcommand
    has no ``-C``/``--ephemeral`` flags — the resumed session's original
    working directory and on-disk persistence are implicit. The subprocess's
    own ``cwd=`` (set by the caller) still controls the actual process cwd.
    """
    return [
        "codex", "exec", "resume", "--json", "--skip-git-repo-check",
        "-m", model, "--dangerously-bypass-approvals-and-sandbox",
        thread_id, "-",
    ]


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


def parse_codex_line(line: str) -> tuple[str, object | None]:
    """Classify one line of codex --json output.

    Returns ('event', dict) for JSON lines, ('stdout', str) for plain text,
    ('ignore', None) for blank lines.
    """
    return classify_json_line(line)


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


_CODEX_PROMPT = (
    "You are an autonomous coding agent (codex). Complete the task in the "
    "workspace and report concisely when finished."
)


class CodexDriver:
    """Driver that shells out to the ``codex`` binary (spec §3.5.3)."""

    name = "codex"
    capabilities = DriverCapabilities(
        supports_tools=False,
        supports_structured_output=False,
        supports_cancel=True,
        requires_image_feature=None,
        supports_mcp=True,
    )
    default_template = DriverTemplate(
        driver="codex",
        default_system_prompt=_CODEX_PROMPT,
        available_tools=[],  # codex owns its tools; list is empty
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
        result = await self._run_codex(
            task=task, config=config, limits=limits, credential=credential, emit=emit,
            cancel=cancel, credential_kind=credential_kind, credential_meta=credential_meta,
            workspace=workspace, skills=skills, mcp_servers=mcp_servers,
            session_id=session_id, resume_thread_id=resume_thread_id,
            latest_thread_id=latest_thread_id,
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
    ) -> TaskResult:
        Path(workspace).mkdir(parents=True, exist_ok=True)

        await emit(
            "status_change",
            {"from": "pending", "to": "running", "result": None, "error": None},
        )

        home = codex_home(workspace)
        sandbox.ensure_agent_dir(home)
        if resume_thread_id:
            cmd = build_resume_command(model=model_arg(config.model), thread_id=resume_thread_id)
        else:
            cmd = build_command(
                workspace=workspace, model=model_arg(config.model),
                ephemeral=session_id is None,
            )
        env = build_env(
            sandbox.build_child_env(),
            credential=credential,
            credential_kind=credential_kind,
            codex_home=home,
        )

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

        # Materialize MCP servers: write config.toml + inject secret env vars
        # (best-effort, like skills). Env vars carry secrets codex reads at startup.
        try:
            count = write_codex_mcp(workspace, mcp_servers or [])
            if count:
                sandbox.chown_to_agent(codex_config_path(workspace))
                env.update(codex_mcp_env(mcp_servers or []))
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

        try:
            proc = await sandbox.spawn_untrusted(
                cmd,
                cwd=workspace,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {"code": "codex_unavailable", "message": "codex binary not found"},
                },
            )
            return TaskResult(success=False, reason="codex_unavailable")

        start = time.monotonic()
        last_text: str | None = None
        error_msg: str | None = None
        tokens_in = 0
        tokens_out = 0
        try:
            # Feed the prompt on stdin, then close so codex can start.
            if proc.stdin is not None:
                proc.stdin.write(task.prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            assert proc.stdout is not None
            while True:
                if cancel.is_set():
                    sandbox.terminate(proc)
                    await emit(
                        "status_change",
                        {"from": "running", "to": "cancelled", "result": None, "error": None},
                    )
                    return TaskResult(success=False, reason="cancelled")

                if time.monotonic() - start >= limits.timeout_seconds:
                    sandbox.terminate(proc)
                    await emit(
                        "log", {"level": "warn", "message": "wall-clock timeout", "data": {}}
                    )
                    await emit(
                        "status_change",
                        {
                            "from": "running",
                            "to": "timed_out",
                            "result": None,
                            "error": {"code": "timeout", "message": "wall-clock timeout"},
                        },
                    )
                    return TaskResult(success=False, reason="timeout")

                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except TimeoutError:
                    if proc.returncode is not None:
                        break
                    continue

                if not raw:
                    break

                line = raw.decode("utf-8", "replace").rstrip("\n")
                kind, value = parse_codex_line(line)
                if kind == "event":
                    assert isinstance(value, dict)
                    await emit("codex_event", {"raw": value})
                    tid = event_thread_id(value)
                    if tid:
                        latest_thread_id["id"] = tid
                    text = event_text(value)
                    if text is not None:
                        last_text = text
                    err = event_error(value)
                    if err is not None:
                        error_msg = err
                    usage = event_usage(value)
                    if usage is not None:
                        tokens_in += usage[0]
                        tokens_out += usage[1]
                        await emit(
                            "token_update",
                            {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        )
                elif kind == "stdout":
                    assert isinstance(value, str)
                    await emit("codex_stdout", {"line": value})

            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception as exc:  # defensive: also catches a startup BrokenPipeError
            sandbox.terminate(proc)
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {"code": "codex_error", "message": str(exc)},
                },
            )
            return TaskResult(success=False, reason="codex_error")

        if rc == 0:
            result = {"success": True, "output": last_text or ""}
            await emit(
                "status_change",
                {"from": "running", "to": "completed", "result": result, "error": None},
            )
            return TaskResult(success=True, output=last_text or "")

        message = error_msg or f"codex exited {rc}"
        await emit(
            "status_change",
            {
                "from": "running",
                "to": "failed",
                "result": None,
                "error": {
                    "code": "codex_error" if error_msg else "codex_nonzero_exit",
                    "message": message,
                },
            },
        )
        return TaskResult(success=False, reason=message)


register(CodexDriver())
