"""Shared, authoritative Pydantic models (index §4). Do not fork these types."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- Task (the public work object — spec §6) -------------------------------
OutputType = Literal["text", "files", "structured"]


class OutputContract(BaseModel):
    type: OutputType = "text"
    # JSON Schema; required when type == "structured".
    # Aliased because `schema` is a reserved BaseModel attribute name.
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    model_config = {"populate_by_name": True}


class TaskLimits(BaseModel):
    max_iterations: int | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None


class TaskBody(BaseModel):
    """What a client POSTs — no driver/model/credential here (spec §6)."""

    prompt: str
    output: OutputContract = OutputContract()
    limits: TaskLimits = TaskLimits()
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ResolvedLimits(BaseModel):
    """After defaults + ceilings applied by the control plane (spec §4.4)."""

    max_iterations: int
    max_tokens: int
    timeout_seconds: int


# ---- Agent config (container config / snapshot — spec §4.9) ----------------
SystemPromptMode = Literal["augment", "replace"]


class ContextSpec(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)
    text: str | None = None
    files: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    driver: str
    model: str
    system_prompt: str = ""
    system_prompt_mode: SystemPromptMode = "augment"
    tools: list[str] = Field(default_factory=list)
    context: ContextSpec = ContextSpec()
    skills: list[str] = Field(default_factory=list)  # opencode skill ids (spec: opencode skills)
    mcp_servers: list[str] = Field(default_factory=list)  # tenant mcp_server ids (opencode/codex)
    # Per-container task-limit overrides. None ⇒ fall back to the tenant default;
    # when set they become this container's default (still capped at the tenant
    # ceiling) for tasks that don't request their own bound. See limits.resolve_limits.
    max_iterations: int | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None


# ---- Git auto-push (workspace git rollback spec) ----------------------------
class GitPushConfig(BaseModel):
    """Per-task push target for the workspace repo's post-task auto-push.

    The SSH private key is held in memory only — same handling rules as
    llm_credential: never persisted, never logged.
    """

    url: str
    ssh_private_key: str
    branch: str = "main"


# ---- Opencode skills (resolved content shipped to the shim) ----------------
class ShimSkill(BaseModel):
    """One resolved skill the opencode/codex driver materializes under the
    discovery dir.

    In-memory only — same handling as llm_credential: never persisted/logged.
    Either ``body`` (inline single SKILL.md) or ``bundle_b64`` (a base64
    gzip-tar of a full skill directory) carries the content; when ``bundle_b64``
    is set it takes precedence over ``body``."""

    name: str
    description: str
    body: str = ""
    bundle_b64: str | None = None


# ---- MCP servers (resolved content shipped to the shim) --------------------
class ShimMcpServer(BaseModel):
    """One resolved remote MCP server the opencode/codex driver wires into its
    native config. In-memory only — same handling as llm_credential: the
    decrypted ``secret`` is never persisted or logged.

    ``auth_type`` is one of: ``none`` (no auth), ``bearer`` (``secret`` is the
    token, sent as ``Authorization: Bearer <secret>``), ``header`` (``secret``
    is sent verbatim as the ``auth_header_name`` header)."""

    name: str
    url: str
    auth_type: str = "none"
    auth_header_name: str = ""
    secret: str = ""


# ---- Shim request (control plane → shim, spec §3.3) ------------------------
class ShimTaskRequest(BaseModel):
    task_id: str
    task: TaskBody
    config: AgentConfig  # the snapshot
    limits: ResolvedLimits
    llm_credential: str  # held in memory only, never persisted/logged
    # Auth method discriminator + non-secret metadata (oauth: account_id, expires_ms).
    credential_kind: Literal["api_key", "oauth_subscription"] = "api_key"
    credential_meta: dict[str, Any] = Field(default_factory=dict)
    # Optional post-task auto-push target (workspace git rollback spec).
    git_push: GitPushConfig | None = None
    # When False (linked-repo / pull mode) the shim does no snapshot work:
    # no baseline ensure_repo, no post-task auto-commit, no auto-push.
    git_snapshots: bool = True
    # Resolved opencode skills (opencode driver only); in-memory, never persisted.
    skills: list[ShimSkill] = Field(default_factory=list)
    # Resolved MCP servers (opencode/codex only); decrypted, in-memory, never persisted.
    mcp_servers: list[ShimMcpServer] = Field(default_factory=list)
    # Driver-sessions: groups this task with prior tasks sharing the same id.
    # `session_is_continuation` is precomputed by the control plane (a cheap
    # `tasks` query) — the driver never queries the DB itself.
    session_id: str | None = None
    session_is_continuation: bool = False


# ---- Status & results ------------------------------------------------------
TaskStatus = Literal[
    "pending", "running", "completed", "failed", "cancelled", "timed_out"
]


class TaskResult(BaseModel):
    success: bool
    output: Any | None = None  # text | files manifest | structured object
    reason: str | None = None


# ---- Events (spec §7) ------------------------------------------------------
EventType = Literal[
    "task_started",
    "iteration_started",
    "assistant_message",
    "tool_call",
    "tool_result",
    "token_update",
    "file_changed",
    "git",
    "opencode_stdout",
    "opencode_event",
    "codex_stdout",
    "codex_event",
    "claude_stdout",
    "claude_event",
    "status_change",
    "log",
]


class Event(BaseModel):
    seq: int  # monotonic per task, starts at 1
    type: EventType
    ts: datetime
    payload: dict[str, Any]
