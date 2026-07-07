from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentcore.models import AgentConfig, ContextSpec, SystemPromptMode


class ResourceLimitsIn(BaseModel):
    mem_limit: str | None = None
    cpus: float | None = None


class CreateContainerRequest(BaseModel):
    name: str
    template_id: str | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: AgentConfig | None = None  # inline override / standalone config
    image_tag: str | None = None
    image_variant: Literal["full", "slim"] = "full"
    volume_id: str | None = None
    resources: dict[str, Any] = Field(default_factory=dict)
    resource_limits: ResourceLimitsIn | None = None


class ContainerOut(BaseModel):
    id: str
    name: str
    external_id: str | None
    metadata: dict[str, Any]
    status: str
    image_tag: str
    image_variant: str
    template_id: str | None
    config: AgentConfig
    last_task_at: str | None
    created_at: str
    error_message: str | None
    git_mode: str = "snapshot"
    mem_limit: str
    cpus: float


class ConfigPatch(BaseModel):
    # A full AgentConfig overwrite (spec §4.9: PATCH overwrites the active config).
    driver: str
    model: str
    system_prompt: str = ""
    system_prompt_mode: SystemPromptMode = "augment"
    tools: list[str] = Field(default_factory=list)
    context: ContextSpec = Field(default_factory=ContextSpec)
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    # Per-container task-limit overrides (None ⇒ use the tenant default).
    max_iterations: int | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None

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
    config: AgentConfig
    assembled_prompt: str


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str
    started_at: str
    credential_used: str | None = None
    session_id: str | None = None


class TaskOut(BaseModel):
    task_id: str
    container_id: str
    container_name: str | None = None
    session_id: str | None = None
    prompt: str
    status: str
    driver: str
    model: str | None
    config_snapshot: AgentConfig
    result: Any | None = None
    error: dict[str, str] | None = None
    iterations_used: int
    tokens_in: int
    tokens_out: int
    started_at: str | None
    ended_at: str | None
    created_at: str


class SessionOut(BaseModel):
    session_id: str
    driver: str
    task_count: int
    first_created_at: str
    last_created_at: str
    busy: bool


class UsageBucketOut(BaseModel):
    start: str
    tokens_in: int
    tokens_out: int
    tasks: int
    iterations: int


class UsageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    interval: str
    series: list[UsageBucketOut]


class BreakdownGroupOut(BaseModel):
    key: str
    label: str
    tokens_in: int
    tokens_out: int
    tasks: int
    iterations: int


class BreakdownResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    by: str
    groups: list[BreakdownGroupOut]


class CreateScheduledTaskRequest(BaseModel):
    name: str
    # Polymorphic target: {"kind": "prompt", ...} or {"kind": "workflow", ...}.
    target: dict[str, Any]
    schedule: dict[str, Any]
    timezone: str
    # For schedule.kind == "once": the ISO-8601 UTC instant to fire at.
    run_at: str | None = None


class UpdateScheduledTaskRequest(BaseModel):
    name: str | None = None
    target: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    timezone: str | None = None
    run_at: str | None = None
    enabled: bool | None = None


class ScheduledTaskOut(BaseModel):
    id: str
    name: str
    target: dict[str, Any]
    schedule: dict[str, Any]
    timezone: str
    enabled: bool
    next_run_at: str | None
    last_run_at: str | None
    last_run_ref: str | None
    last_status: str | None
    created_at: str


class WorkflowStepIn(BaseModel):
    prompt_id: str
    container_id: str
    variables: dict[str, str] = Field(default_factory=dict)


class CreateWorkflowRequest(BaseModel):
    name: str
    description: str | None = None
    steps: list[WorkflowStepIn]


class UpdateWorkflowRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStepIn] | None = None


class WorkflowOut(BaseModel):
    id: str
    name: str
    description: str | None
    steps: list[dict[str, Any]]
    created_by: str | None
    created_at: str | None
    updated_at: str | None


class RunWorkflowRequest(BaseModel):
    trigger_source: Literal["api", "manual"] = "api"


class WorkflowRunOut(BaseModel):
    id: str
    workflow_id: str
    status: str
    cursor: int
    step_count: int
    current_task_id: str | None
    error_step: int | None
    error_message: str | None
    trigger_source: str
    scheduled_task_id: str | None
    started_at: str | None
    ended_at: str | None


class WorkflowRunStepOut(BaseModel):
    step_index: int
    task_id: str | None
    container_id: str | None
    status: str
    started_at: str | None
    ended_at: str | None


class WorkflowRunDetailOut(WorkflowRunOut):
    steps: list[WorkflowRunStepOut] | None
