from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentcore.models import AgentConfig, ContextSpec, SystemPromptMode


class ResourceLimitsIn(BaseModel):
    mem_limit: str | None = Field(
        None,
        description=(
            "Memory limit as a Docker size string (e.g. `512m`, `2g`). Clamped to "
            "the tenant/platform bounds. Omit to keep the current value."
        ),
        examples=["1g"],
    )
    cpus: float | None = Field(
        None,
        description=(
            "CPU allowance in fractional cores (e.g. `0.5`, `2`). Clamped to the "
            "tenant/platform bounds. Omit to keep the current value."
        ),
        examples=[1.0],
    )


class CreateContainerRequest(BaseModel):
    name: str = Field(
        description="Human-readable name for the agent container.", examples=["research-bot"]
    )
    template_id: str | None = Field(
        None,
        description=(
            "Seed the container's config from this template. Provide either "
            "`template_id` or an inline `config`; an inline `config` overrides the template."
        ),
    )
    external_id: str | None = Field(
        None,
        description=(
            "Your own idempotency/reference key. At most one live (non-destroyed) "
            "container may use a given `external_id` per tenant."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key/value metadata stored verbatim on the container.",
    )
    config: AgentConfig | None = Field(
        None,
        description=(
            "Inline agent configuration (driver, model, tools, prompt, skills, MCP "
            "servers). When present it is the complete active config and overrides `template_id`."
        ),
    )
    image_tag: str | None = Field(
        None,
        description="Agent image tag to run. Defaults to the platform's configured agent image.",
    )
    image_variant: Literal["full", "slim"] = Field(
        "full",
        description=(
            "Image variant. `full` includes headless Chromium (for JS-rendered web "
            "fetch); `slim` is smaller but rejects configs that need Chromium."
        ),
    )
    volume_id: str | None = Field(
        None,
        description="Reuse an existing workspace volume by name instead of creating a fresh one.",
    )
    resources: dict[str, Any] = Field(
        default_factory=dict,
        description="Advanced/host resource hints stored on the container (rarely needed).",
    )
    resource_limits: ResourceLimitsIn | None = Field(
        None,
        description="Optional memory/CPU limits for the container. Falls back to variant defaults.",
    )


class ContainerOut(BaseModel):
    id: str = Field(description="Container (agent) id.")
    name: str = Field(description="Human-readable container name.")
    external_id: str | None = Field(description="Caller-supplied external reference key, if any.")
    metadata: dict[str, Any] = Field(
        description="Arbitrary key/value metadata stored on the container."
    )
    status: str = Field(
        description=(
            "Lifecycle status: `running`, `pausing`, `paused`, `archived`, `error`, "
            "or `destroyed`."
        ),
    )
    image_tag: str = Field(description="Agent image tag the container runs.")
    image_variant: str = Field(description="Image variant (`full` or `slim`).")
    template_id: str | None = Field(description="Template the container was seeded from, if any.")
    config: AgentConfig = Field(description="The container's active agent configuration.")
    last_task_at: str | None = Field(
        description="ISO-8601 timestamp of the most recent task, or null if none."
    )
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    error_message: str | None = Field(
        description="Diagnostic detail when `status` is `error`, else null."
    )
    git_mode: str = Field("snapshot", description="Workspace git mode: `snapshot` or `linked`.")
    mem_limit: str = Field(description="Effective memory limit (Docker size string).")
    cpus: float = Field(description="Effective CPU allowance in fractional cores.")


class ConfigPatch(BaseModel):
    # A full AgentConfig overwrite (spec §4.9: PATCH overwrites the active config).
    driver: str = Field(description="Agent driver to run (e.g. the vanilla loop driver).")
    model: str = Field(description="LLM model id the agent uses. Must be allowed for the tenant.")
    system_prompt: str = Field("", description="Custom system prompt text.")
    system_prompt_mode: SystemPromptMode = Field(
        "augment",
        description=(
            "`augment` appends to the driver's default prompt; `replace` overrides "
            "it entirely."
        ),
    )
    tools: list[str] = Field(default_factory=list, description="Tool names enabled for the agent.")
    context: ContextSpec = Field(
        default_factory=ContextSpec, description="Context-window / history configuration."
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Skill ids to attach. Ids not owned by the tenant are silently dropped.",
    )
    mcp_servers: list[str] = Field(
        default_factory=list,
        description="MCP server ids to attach. Ids not owned by the tenant are silently dropped.",
    )
    # Per-container task-limit overrides (None ⇒ use the tenant default).
    max_iterations: int | None = Field(
        None,
        description="Per-container cap on agent loop iterations. Null uses the tenant default.",
    )
    max_tokens: int | None = Field(
        None,
        description="Per-container cap on total tokens per task. Null uses the tenant default.",
    )
    timeout_seconds: int | None = Field(
        None, description="Per-container task timeout in seconds. Null uses the tenant default."
    )

    def to_agent_config(self) -> AgentConfig:
        return AgentConfig(
            driver=self.driver,
            model=self.model,
            system_prompt=self.system_prompt,
            system_prompt_mode=self.system_prompt_mode,
            tools=self.tools,
            context=self.context,
            skills=self.skills,
            mcp_servers=self.mcp_servers,
            max_iterations=self.max_iterations,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
        )


class ConfigOut(BaseModel):
    config: AgentConfig = Field(description="The container's active agent configuration.")
    assembled_prompt: str = Field(
        description="Preview of the fully assembled system prompt that would be sent to the model."
    )


class TaskSubmitResponse(BaseModel):
    task_id: str = Field(description="Id of the newly created task.")
    status: str = Field(description="Initial task status (typically `running` or `pending`).")
    started_at: str = Field(description="ISO-8601 timestamp the task was accepted.")
    credential_used: str | None = Field(
        None, description="Id of the LLM credential selected for the run, if resolved."
    )
    session_id: str | None = Field(
        None, description="Session the task was attached to, when a session was used."
    )


class TaskOut(BaseModel):
    task_id: str = Field(description="Task id.")
    container_id: str = Field(description="Container the task ran on.")
    container_name: str | None = Field(None, description="Name of the container, when available.")
    session_id: str | None = Field(None, description="Session id the task belongs to, if any.")
    prompt: str = Field(description="The prompt submitted for this task.")
    status: str = Field(
        description="Task status: `pending`, `running`, `succeeded`, `failed`, or `cancelled`."
    )
    driver: str = Field(description="Driver that executed the task.")
    model: str | None = Field(description="Model used, if resolved.")
    config_snapshot: AgentConfig = Field(
        description="The agent config captured at submission time."
    )
    result: Any | None = Field(None, description="Task result payload on success, else null.")
    error: dict[str, str] | None = Field(
        None, description="Error `{code, message}` on failure, else null."
    )
    iterations_used: int = Field(description="Number of agent loop iterations consumed.")
    tokens_in: int = Field(description="Prompt/input tokens consumed.")
    tokens_out: int = Field(description="Completion/output tokens produced.")
    started_at: str | None = Field(description="ISO-8601 start timestamp, or null if not started.")
    ended_at: str | None = Field(description="ISO-8601 end timestamp, or null if still running.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")


class SessionOut(BaseModel):
    session_id: str = Field(
        description="Session id (groups related tasks that share driver state)."
    )
    driver: str = Field(description="Driver the session is bound to.")
    task_count: int = Field(description="Number of tasks in the session.")
    first_created_at: str = Field(description="ISO-8601 timestamp of the session's first task.")
    last_created_at: str = Field(
        description="ISO-8601 timestamp of the session's most recent task."
    )
    busy: bool = Field(description="Whether a task in the session is currently in flight.")


class UsageBucketOut(BaseModel):
    start: str = Field(description="ISO-8601 start of the time bucket.")
    tokens_in: int = Field(description="Input tokens in the bucket.")
    tokens_out: int = Field(description="Output tokens in the bucket.")
    tasks: int = Field(description="Number of tasks in the bucket.")
    iterations: int = Field(description="Number of agent iterations in the bucket.")


class UsageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(
        alias="from",
        description="ISO-8601 start of the reported range (serialized as `from`).",
    )
    to: str = Field(description="ISO-8601 end of the reported range.")
    interval: str = Field(description="Bucket granularity: `hour` or `day`.")
    series: list[UsageBucketOut] = Field(description="Ordered usage buckets over the range.")


class BreakdownGroupOut(BaseModel):
    key: str = Field(description="Group key (e.g. a container id, driver, model, or status value).")
    label: str = Field(description="Human-readable label for the group.")
    tokens_in: int = Field(description="Input tokens attributed to the group.")
    tokens_out: int = Field(description="Output tokens attributed to the group.")
    tasks: int = Field(description="Task count for the group.")
    iterations: int = Field(description="Agent iteration count for the group.")


class BreakdownResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(
        alias="from",
        description="ISO-8601 start of the reported range (serialized as `from`).",
    )
    to: str = Field(description="ISO-8601 end of the reported range.")
    by: str = Field(
        description=(
            "Dimension the usage is grouped by: `container`, `driver`, `model`, "
            "or `status`."
        )
    )
    groups: list[BreakdownGroupOut] = Field(description="Usage totals per group.")


class CreateScheduledTaskRequest(BaseModel):
    name: str = Field(description="Human-readable name for the schedule.")
    # Polymorphic target: {"kind": "prompt", ...} or {"kind": "workflow", ...}.
    target: dict[str, Any] = Field(
        description=(
            "What to run when the schedule fires. Either `{\"kind\": \"prompt\", …}` "
            "or `{\"kind\": \"workflow\", …}`."
        ),
    )
    schedule: dict[str, Any] = Field(
        description=(
            "Schedule definition, e.g. `{\"kind\": \"cron\", \"expr\": \"0 9 * * *\"}` "
            "or `{\"kind\": \"once\"}`."
        ),
    )
    timezone: str = Field(
        description="IANA timezone the schedule is evaluated in (e.g. `America/New_York`)."
    )
    # For schedule.kind == "once": the ISO-8601 UTC instant to fire at.
    run_at: str | None = Field(
        None, description="For a one-shot (`once`) schedule, the ISO-8601 UTC instant to fire at."
    )


class UpdateScheduledTaskRequest(BaseModel):
    name: str | None = Field(None, description="New name. Omit to leave unchanged.")
    target: dict[str, Any] | None = Field(None, description="New target. Omit to leave unchanged.")
    schedule: dict[str, Any] | None = Field(
        None, description="New schedule. Omit to leave unchanged."
    )
    timezone: str | None = Field(None, description="New timezone. Omit to leave unchanged.")
    run_at: str | None = Field(None, description="New one-shot fire time. Omit to leave unchanged.")
    enabled: bool | None = Field(
        None, description="Enable or disable the schedule. Omit to leave unchanged."
    )


class ScheduledTaskOut(BaseModel):
    id: str = Field(description="Scheduled-task id.")
    name: str = Field(description="Schedule name.")
    target: dict[str, Any] = Field(
        description="What the schedule runs (prompt or workflow target)."
    )
    schedule: dict[str, Any] = Field(description="The schedule definition.")
    timezone: str = Field(description="IANA timezone the schedule is evaluated in.")
    enabled: bool = Field(description="Whether the schedule is currently active.")
    next_run_at: str | None = Field(
        description="ISO-8601 timestamp of the next fire, or null if none/disabled."
    )
    last_run_at: str | None = Field(description="ISO-8601 timestamp of the last fire, or null.")
    last_run_ref: str | None = Field(
        description="Id of the task/workflow-run produced by the last fire, or null."
    )
    last_status: str | None = Field(description="Status of the last fire, or null.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")


class WorkflowStepIn(BaseModel):
    prompt_id: str = Field(description="Id of the saved prompt to run in this step.")
    container_id: str = Field(description="Container the step's task runs on.")
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="Variable substitutions applied to the prompt for this step.",
    )


class CreateWorkflowRequest(BaseModel):
    name: str = Field(description="Human-readable workflow name.")
    description: str | None = Field(
        None, description="Optional description of what the workflow does."
    )
    steps: list[WorkflowStepIn] = Field(
        description="Ordered steps executed sequentially when the workflow runs."
    )


class UpdateWorkflowRequest(BaseModel):
    name: str | None = Field(None, description="New name. Omit to leave unchanged.")
    description: str | None = Field(None, description="New description. Omit to leave unchanged.")
    steps: list[WorkflowStepIn] | None = Field(
        None, description="Replacement step list. Omit to leave unchanged."
    )


class WorkflowOut(BaseModel):
    id: str = Field(description="Workflow id.")
    name: str = Field(description="Workflow name.")
    description: str | None = Field(description="Workflow description, if set.")
    steps: list[dict[str, Any]] = Field(description="The workflow's ordered steps.")
    created_by: str | None = Field(
        description="Id of the principal that created the workflow, if known."
    )
    created_at: str | None = Field(description="ISO-8601 creation timestamp.")
    updated_at: str | None = Field(description="ISO-8601 last-update timestamp.")


class RunWorkflowRequest(BaseModel):
    trigger_source: Literal["api", "manual"] = Field(
        "api",
        description=(
            "Records what initiated the run: `api` (programmatic) or `manual` "
            "(user-triggered)."
        ),
    )


class WorkflowRunOut(BaseModel):
    id: str = Field(description="Workflow-run id.")
    workflow_id: str = Field(description="Workflow this run belongs to.")
    status: str = Field(description="Run status: `running`, `succeeded`, `failed`, or `cancelled`.")
    cursor: int = Field(description="Index of the step currently executing (0-based).")
    step_count: int = Field(description="Total number of steps in the run.")
    current_task_id: str | None = Field(description="Task id of the step in flight, or null.")
    error_step: int | None = Field(description="Index of the step that failed, or null.")
    error_message: str | None = Field(description="Failure detail, or null.")
    trigger_source: str = Field(
        description="What initiated the run (`api`, `manual`, or a schedule)."
    )
    scheduled_task_id: str | None = Field(description="Schedule that triggered the run, if any.")
    started_at: str | None = Field(description="ISO-8601 start timestamp, or null.")
    ended_at: str | None = Field(description="ISO-8601 end timestamp, or null if still running.")


class WorkflowRunStepOut(BaseModel):
    step_index: int = Field(description="0-based position of the step in the workflow.")
    task_id: str | None = Field(
        description="Task produced by this step, or null if not yet started."
    )
    container_id: str | None = Field(description="Container the step ran on, or null.")
    status: str = Field(
        description="Step status: `pending`, `running`, `succeeded`, `failed`, or `cancelled`."
    )
    started_at: str | None = Field(description="ISO-8601 start timestamp, or null.")
    ended_at: str | None = Field(description="ISO-8601 end timestamp, or null.")


class WorkflowRunDetailOut(WorkflowRunOut):
    steps: list[WorkflowRunStepOut] | None = Field(
        description="Per-step detail for the run, or null."
    )
