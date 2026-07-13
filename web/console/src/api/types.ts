// Mirrors index §4 (agentcore/models.py) + §5 (driver/tool metadata) + §6.2 wire shapes.
// On the wire, OutputContract serializes `schema` (Pydantic alias), not `json_schema`.

export type OutputType = "text" | "files" | "structured";
export interface OutputContract { type: OutputType; schema?: Record<string, unknown> | null; }
export interface TaskLimits { max_iterations?: number | null; max_tokens?: number | null; timeout_seconds?: number | null; }

export type SystemPromptMode = "augment" | "replace";
export interface ContextSpec { variables: Record<string, string>; text: string | null; files: string[]; }

export type Effort = "low" | "medium" | "high" | "max";
// Drivers whose CLI accepts the unified effort param (mirror of the backend gate).
export const EFFORT_DRIVERS: string[] = ["opencode", "claude-code", "codex"];

export interface AgentConfig {
  driver: string; model: string; system_prompt: string;
  system_prompt_mode: SystemPromptMode; tools: string[]; context: ContextSpec;
  skills?: string[];
  mcp_servers?: string[];
  // Reasoning effort passed to the CLI, for drivers in EFFORT_DRIVERS. null/undefined ⇒ the model's own default.
  effort?: Effort | null;
  // Per-container task-limit overrides (null/undefined ⇒ use the tenant default).
  max_iterations?: number | null;
  max_tokens?: number | null;
  timeout_seconds?: number | null;
}

export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "timed_out";
export interface TaskResult { success: boolean; output?: unknown; reason?: string | null; }

export type EventType =
  | "task_started" | "iteration_started" | "assistant_message" | "tool_call"
  | "tool_result" | "token_update" | "file_changed" | "git" | "opencode_stdout"
  | "opencode_event" | "codex_stdout" | "codex_event" | "claude_stdout" | "claude_event" | "status_change" | "log";
export interface Event { seq: number; type: EventType; ts: string; payload: Record<string, unknown>; }

export type ContainerStatus =
  | "provisioning" | "resuming" | "running" | "pausing" | "paused"
  | "archiving" | "archived" | "recovering" | "error" | "destroying" | "deleting" | "destroyed";

export interface Container {
  id: string; name: string; external_id: string | null; status: ContainerStatus;
  image_variant: "full" | "slim"; image_tag: string; config: AgentConfig;
  metadata: Record<string, unknown>; last_task_at: string | null;
  created_at: string; error_message: string | null;
  git_mode?: "snapshot" | "linked";
  mem_limit: string;
  cpus: number;
}
export interface ContainerConfigResponse { config: AgentConfig; assembled_prompt: string; }

export interface DriverCapabilities {
  supports_tools: boolean; supports_structured_output: boolean;
  supports_cancel: boolean; requires_image_feature: string | null;
}
export interface DriverTemplate {
  driver: string; default_system_prompt: string; available_tools: string[];
  tools_user_editable: boolean; supports_context: boolean;
}
export interface ToolSpec {
  name: string; description: string; input_schema: Record<string, unknown>;
  requires_image_feature: string | null;
}
export interface Template {
  id: string; tenant_id: string | null; name: string; driver: string; model: string | null;
  system_prompt: string; system_prompt_mode: SystemPromptMode; tools: string[];
  context: ContextSpec; skills: string[]; mcp_servers: string[]; limits: TaskLimits; is_builtin: boolean;
  image_variant?: "full" | "slim" | null; mem_limit?: string | null; cpus?: number | null;
  effort?: Effort | null;
  capabilities: DriverCapabilities; driver_template: DriverTemplate; available_tool_specs: ToolSpec[];
}

// Form-state shape for creating/editing a template. `model` is a string in the
// form ("" = none) and is serialized to null on save. `effort` mirrors
// AgentConfig's own null-is-unset convention (unlike model/image_variant/etc,
// which use "" for the form binding) so the draft can be handed straight to
// ConfigFields, which is shared with AgentConfig-backed callers.
export interface TemplateDraft {
  name: string; driver: string; model: string;
  system_prompt: string; system_prompt_mode: SystemPromptMode;
  tools: string[]; context: ContextSpec; skills: string[]; mcp_servers: string[]; limits: TaskLimits;
  image_variant: "" | "full" | "slim"; mem_limit: string; cpus: string;
  effort: Effort | null;
}

// Wire payload for saving a template: like the draft, but `model` is null when unset.
export type TemplateSavePayload = Omit<TemplateDraft, "model" | "image_variant" | "mem_limit" | "cpus"> & {
  model: string | null;
  image_variant: "full" | "slim" | null; mem_limit: string | null; cpus: number | null;
};

export type Role = "owner" | "admin" | "member";
export interface TenantLimits {
  allowed_drivers: string[];
  default_max_iterations: number; default_max_tokens: number;
  default_task_timeout_seconds: number; max_concurrent_tasks_per_container: number;
}
export interface ModelOption {
  id: string;
  provider: string;
  label: string;
  category: "free" | "api_key" | "subscription";
  drivers: string[];
  available: boolean;
  requires: string[];
}
export interface Tenant { id: string; name: string; limits: TenantLimits; }
export interface Me {
  id: string; tenant_id: string | null; name: string; email: string;
  role: Role; is_staff: boolean; must_change_password: boolean; tenant: Tenant | null;
  active_tenant_id: string | null;
  tenants: Array<{ id: string; name: string; role: Role }>;
}

export interface TaskSummary {
  task_id: string; status: TaskStatus; prompt: string; started_at: string;
  ended_at: string | null; tokens_in: number; tokens_out: number;
  iterations_used: number; config_snapshot?: AgentConfig; session_id?: string | null;
}
export interface TaskDetail extends TaskSummary {
  result: TaskResult | null; error: { code: string; message: string } | null;
}

export interface SessionSummary {
  session_id: string; driver: string; task_count: number;
  first_created_at: string; last_created_at: string; busy: boolean;
}

export interface FileEntry { path: string; size: number; is_dir?: boolean; modified_at: string; content_type: string; }

export interface ApiKeyRow {
  id: string; name: string; prefix: string; last_used_at: string | null;
  created_at: string; created_by: string; status: "active" | "revoked";
}
export interface ApiKeyCreated { id: string; name: string; key: string; prefix: string; created_at: string; }

export interface Credential {
  id: string;
  provider: string;
  auth_method: "api_key" | "oauth_subscription";
  status: "active" | "reauth_required";
  last4: string | null;
  account_tail: string | null;
  expires_at: string | null;
  created_by: string;
  created_at: string;
}

// Providers a tenant can store an API key for, derived from the model catalog
// (GET /v1/credentials/providers). Drives the credentials provider dropdown.
export interface CredentialProvider {
  id: string;
  label: string;
}

export interface OAuthStartResponse {
  connection_id: string;
  user_code: string;
  verification_uri: string | null;
  verification_uri_complete: string | null;
  expires_in: number;
  interval: number;
}

export interface OAuthConnectionStatus {
  connection_id: string;
  status: "pending" | "connected" | "timeout" | "failed";
  error: string | null;
  credential_id: string | null;
}

export interface AnthropicOAuthStart {
  connection_id: string;
  authorize_url: string;
}

export interface AnthropicOAuthComplete {
  connection_id: string;
  status: "connected" | "failed";
  credential_id: string | null;
  error: string | null;
}

export interface User {
  id: string; name: string; email: string; role: Role; status: "active" | "disabled";
}

export interface StaffUser {
  id: string; name: string; email: string; status: "active" | "disabled";
  must_change_password: boolean; created_at: string;
}

export interface ApiErrorBody { error: { code: string; message: string; field?: string }; }

// ---- Opencode skills --------------------------------------------------------
// The list endpoint returns the summary (no `body`); GET /v1/skills/:id adds it.
export type SkillSourceType = "inline" | "git";

export interface Skill {
  id: string;
  name: string;
  description: string;
  body?: string;
  enabled: boolean;
  source_type: SkillSourceType;
  source_url?: string | null;
  source_subpath?: string | null;
  source_ref?: string | null;
  deploy_key_id?: string | null;
  pinned_sha?: string | null;
  bundle_size?: number | null;
  created_at: string | null;
  updated_at: string | null;
}

// ---- MCP servers ------------------------------------------------------------
// The secret is write-only: never returned. `secret_set` reports whether one is stored.
export type McpAuthType = "none" | "bearer" | "header";

// ---- Prompt library ---------------------------------------------------------
export interface PromptVariable { name: string; label?: string; default?: string; }
export interface Prompt {
  id: string;
  name: string;
  body: string;
  tags: string[];
  variables: PromptVariable[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpServer {
  id: string;
  name: string;
  description: string;
  url: string;
  auth_type: McpAuthType;
  auth_header_name?: string | null;
  secret_set: boolean;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface UsageSeriesPoint {
  start: string;
  tokens_in: number;
  tokens_out: number;
  tasks: number;
  iterations: number;
}
export interface UsageResponse {
  from: string;
  to: string;
  interval: "hour" | "day";
  series: UsageSeriesPoint[];
}
export interface BreakdownGroup {
  key: string;
  label: string;
  tokens_in: number;
  tokens_out: number;
  tasks: number;
  iterations: number;
}
export interface BreakdownResponse {
  from: string;
  to: string;
  by: "container" | "driver" | "model" | "status";
  groups: BreakdownGroup[];
}
export interface TenantTaskSummary {
  task_id: string;
  container_id: string;
  container_name: string | null;
  status: TaskStatus;
  prompt: string;
  tokens_in: number;
  tokens_out: number;
  created_at: string;
}

// ---- Workspace git (workspace git rollback spec) ----------------------------
export interface GitSnapshot {
  sha: string;
  ts: number; // unix seconds
  message: string;
  task_id: string | null;
  files_changed: number;
}

export interface GitRemote {
  url: string;
  branch: string;
  ssh_public_key: string | null;
  key_fingerprint: string | null;
  key_type: string | null;
  enabled: boolean;
  verified_at: string | null;
  needs_relink: boolean;
  last_push_status: "pushed" | "failed" | null;
  last_push_error: string | null;
  last_push_at: string | null;
}

// ---- Linked git repo (pull mode) --------------------------------------------
export interface LinkedRepo {
  url: string;
  branch: string;
  ssh_public_key: string | null;
  key_fingerprint: string | null;
  key_type: string | null;
  verified_at: string | null;
  linked_at: string | null;
  last_clone_status: string | null;
  last_clone_error: string | null;
  last_clone_at: string | null;
}

export type ScheduleUnit = "hour" | "day" | "week" | "month";

export interface ScheduleSpec {
  kind: "once" | "recurring";
  unit?: ScheduleUnit;
  time?: string;          // "HH:MM"
  weekdays?: number[];    // ISO 1..7 (weekly)
  day_of_month?: number;  // 1..31 (monthly)
}

export type ScheduleTarget =
  | { kind: "prompt"; container_id: string; prompt_id: string; variables: Record<string, string> }
  | { kind: "workflow"; workflow_id: string };

export interface ScheduledTask {
  id: string;
  name: string;
  target: ScheduleTarget;
  schedule: ScheduleSpec;
  timezone: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_ref: string | null;
  last_status: string | null;
  created_at: string;
}

export interface ScheduledTaskCreate {
  name: string;
  target: ScheduleTarget;
  schedule: ScheduleSpec;
  timezone: string;
  run_at?: string | null;
}

export interface ScheduledTaskUpdate {
  name?: string;
  target?: ScheduleTarget;
  schedule?: ScheduleSpec;
  timezone?: string;
  run_at?: string | null;
  enabled?: boolean;
}

export interface ImageTag {
  tag: string;
  source: "registry" | "local";
}

// ---- Workflows ---------------------------------------------------------------
export interface WorkflowStep { prompt_id: string; container_id: string; variables: Record<string, string>; }
export interface Workflow {
  id: string; name: string; description: string | null;
  steps: WorkflowStep[]; created_by: string | null; created_at: string; updated_at: string;
}
export interface WorkflowRun {
  id: string; workflow_id: string; status: "running" | "completed" | "failed";
  cursor: number; step_count: number; current_task_id: string | null;
  error_step: number | null; error_message: string | null;
  trigger_source: string; scheduled_task_id: string | null;
  started_at: string | null; ended_at: string | null;
}
export interface WorkflowRunStep {
  step_index: number;
  task_id: string | null;
  container_id: string | null;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string | null;
  ended_at: string | null;
}
export interface WorkflowRunDetail extends WorkflowRun {
  steps: WorkflowRunStep[] | null;
}
export interface WorkflowCreate { name: string; description?: string | null; steps: WorkflowStep[]; }

export interface ImageTagsResponse {
  tags: ImageTag[];
  default_tag: string;
  registry_unavailable: boolean;
}
