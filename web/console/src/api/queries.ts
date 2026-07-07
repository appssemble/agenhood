import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "./client";
import { containerFileRawPath } from "./fileUrls";
import type {
  Container, ContainerConfigResponse, AgentConfig, Template, TaskSummary,
  TaskDetail, FileEntry, ApiKeyRow, ApiKeyCreated, Credential, CredentialProvider, User, StaffUser, Me,
  UsageResponse, BreakdownResponse, TenantTaskSummary,
  OAuthStartResponse, OAuthConnectionStatus, AnthropicOAuthStart, AnthropicOAuthComplete, ModelOption,
  GitRemote, LinkedRepo, GitSnapshot, Skill, TemplateSavePayload, Event,
  ScheduledTask, ScheduledTaskCreate, ScheduledTaskUpdate, Role, ImageTagsResponse,
  McpServer, McpAuthType,
  Prompt, PromptVariable,
  Workflow, WorkflowRun, WorkflowRunDetail, WorkflowCreate,
  SessionSummary,
} from "./types";
import { rangeToParams, type Range } from "../lib/range";
import { fetchRecommendedSkills } from "../lib/recommendedSkills";

export const keys = {
  me: ["me"] as const,
  containers: ["containers"] as const,
  container: (cid: string) => ["containers", cid] as const,
  config: (cid: string) => ["containers", cid, "config"] as const,
  tasks: (cid: string, sessionId?: string) =>
    sessionId ? (["containers", cid, "tasks", { sessionId }] as const) : (["containers", cid, "tasks"] as const),
  sessions: (cid: string) => ["containers", cid, "sessions"] as const,
  task: (cid: string, tid: string) => ["containers", cid, "tasks", tid] as const,
  scheduledTasks: () => ["scheduled-tasks"] as const,
  scheduledTask: (sid: string) => ["scheduled-tasks", sid] as const,
  files: (cid: string, prefix: string) => ["containers", cid, "files", prefix] as const,
  imageTags: ["images", "tags"] as const,
  templates: ["templates"] as const,
  template: (id: string) => ["templates", id] as const,
  skills: ["skills"] as const,
  mcpServers: ["mcp-servers"] as const,
  prompts: ["prompts"] as const,
  workflows: ["workflows"] as const,
  workflow: (wid: string) => ["workflows", wid] as const,
  workflowRuns: (wid: string) => ["workflows", wid, "runs"] as const,
  workflowRun: (wid: string, rid: string) => ["workflows", wid, "runs", rid] as const,
  apiKeys: ["api-keys"] as const,
  credentials: ["credentials"] as const,
  deployKeys: ["deploy-keys"] as const,
  users: ["users"] as const,
  usage: (range: string) => ["analytics", "usage", range] as const,
  breakdown: (by: string, range: string) => ["analytics", "breakdown", by, range] as const,
  tenantTasks: (limit: number) => ["tasks", "tenant", limit] as const,
  models: (driver: string) => ["models", driver] as const,
  gitSnapshots: (cid: string) => ["containers", cid, "git", "snapshots"] as const,
  gitRemote: (cid: string) => ["containers", cid, "git", "remote"] as const,
  gitLink: (cid: string) => ["containers", cid, "git", "link"] as const,
  adminTenants: ["admin", "tenants"] as const,
  staffUsers: ["admin", "staff"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api.get<Me>("/v1/auth/me") });

export const useAllTenants = (enabled: boolean) =>
  useQuery({
    queryKey: keys.adminTenants,
    queryFn: () => api.get<{ tenants: { id: string; name: string }[] }>("/admin/v1/tenants"),
    enabled,
  });

export function useSelectTenant() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (tenantId: string | null) =>
      api.post<{ active_tenant_id: string | null; role: Role | null }>(
        "/v1/auth/select-tenant", { tenant_id: tenantId }),
    onSuccess: () => {
      for (const key of [
        keys.containers, keys.templates, keys.users, keys.apiKeys, keys.credentials,
        keys.skills, ["tasks"], ["models"], ["analytics"], keys.me,
      ]) {
        qc.invalidateQueries({ queryKey: key as readonly unknown[] });
      }
      navigate("/");
    },
  });
}

export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<{ id: string; name: string; owner_id: string }>("/v1/tenants", { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.adminTenants });
      qc.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export const useContainers = () => useQuery({ queryKey: keys.containers, queryFn: () => api.get<{ containers: Container[] }>("/v1/containers"), refetchInterval: 30_000 });
export const useContainer = (cid: string) => useQuery({ queryKey: keys.container(cid), queryFn: () => api.get<Container>(`/v1/containers/${cid}`) });
export const useTemplates = () => useQuery({ queryKey: keys.templates, queryFn: () => api.get<{ templates: Template[] }>("/v1/templates") });
export const useTemplate = (id: string) =>
  useQuery({ queryKey: keys.template(id), queryFn: () => api.get<Template>(`/v1/templates/${id}`), enabled: !!id });
export const useTasks = (cid: string, sessionId?: string) => useQuery({
  queryKey: keys.tasks(cid, sessionId),
  queryFn: () => api.get<{ tasks: TaskSummary[] }>(
    `/v1/containers/${cid}/tasks${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`
  ),
});

export const useSessions = (cid: string) => useQuery({
  queryKey: keys.sessions(cid),
  queryFn: () => api.get<{ sessions: SessionSummary[] }>(`/v1/containers/${cid}/sessions`),
});
export const useTask = (cid: string, tid: string) => useQuery({ queryKey: keys.task(cid, tid), queryFn: () => api.get<TaskDetail>(`/v1/containers/${cid}/tasks/${tid}`) });
// Replays a finished task's stored events (non-SSE GET). Used by the chat
// layout to show a past turn's intermediate steps without opening a stream.
export const useTaskEvents = (cid: string, tid: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.task(cid, tid), "events"],
    queryFn: () => api.get<{ events: Event[] }>(`/v1/containers/${cid}/tasks/${tid}/events`),
    enabled,
  });
export const useFiles = (cid: string, prefix = "") => useQuery({ queryKey: keys.files(cid, prefix), queryFn: () => api.get<{ files: FileEntry[] }>(`/v1/containers/${cid}/files?prefix=${encodeURIComponent(prefix)}`) });

export function useDeleteFile(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      api.del(containerFileRawPath(cid, path)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.files(cid, "") });
    },
  });
}
export const useApiKeys = () => useQuery({ queryKey: keys.apiKeys, queryFn: () => api.get<{ keys: ApiKeyRow[] }>("/v1/api-keys") });
export const useCredentials = () => useQuery({ queryKey: keys.credentials, queryFn: () => api.get<{ credentials: Credential[] }>("/v1/credentials") });
export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: () => api.get<{ users: User[] }>("/v1/users") });
export const useStaffUsers = () => useQuery({ queryKey: keys.staffUsers, queryFn: () => api.get<{ staff: StaffUser[] }>("/admin/v1/staff") });

export const useAnalyticsUsage = (range: Range) =>
  useQuery({
    queryKey: keys.usage(range),
    queryFn: () => {
      const { from, to, interval } = rangeToParams(range);
      const qs = new URLSearchParams({ from, to, interval });
      return api.get<UsageResponse>(`/v1/analytics/usage?${qs}`);
    },
    refetchInterval: 30_000,
  });

export const useAnalyticsBreakdown = (by: "container" | "status", range: Range) =>
  useQuery({
    queryKey: keys.breakdown(by, range),
    queryFn: () => {
      const { from, to } = rangeToParams(range);
      const qs = new URLSearchParams({ from, to, by });
      return api.get<BreakdownResponse>(`/v1/analytics/breakdown?${qs}`);
    },
    refetchInterval: 30_000,
  });

export const useTenantTasks = (limit = 12) =>
  useQuery({
    queryKey: keys.tenantTasks(limit),
    queryFn: () => api.get<{ tasks: TenantTaskSummary[] }>(`/v1/tasks?limit=${limit}`),
    refetchInterval: 30_000,
  });

export function useSaveConfig(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: AgentConfig) => api.patch<ContainerConfigResponse>(`/v1/containers/${cid}/config`, config),
    onSuccess: () => { qc.invalidateQueries({ queryKey: keys.config(cid) }); qc.invalidateQueries({ queryKey: keys.container(cid) }); },
  });
}
// Create (POST) when no id, update (PATCH) when an id is supplied. `body` is the
// serialized template payload (model already null-coalesced).
export function useSaveTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: TemplateSavePayload }) =>
      id ? api.patch<Template>(`/v1/templates/${id}`, body) : api.post<Template>("/v1/templates", body),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: keys.templates });
      if (id) qc.invalidateQueries({ queryKey: keys.template(id) });
    },
  });
}
export function useSubmitTask(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) =>
      api.post<{ task_id: string; status: string; session_id: string | null }>(
        `/v1/containers/${cid}/tasks`, body
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.tasks(cid) });
      qc.invalidateQueries({ queryKey: keys.sessions(cid) });
    },
  });
}
export function useCancelTask(cid: string, tid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/v1/containers/${cid}/tasks/${tid}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.task(cid, tid) }),
  });
}
export function useLifecycle(cid: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: keys.containers }); qc.invalidateQueries({ queryKey: keys.container(cid) }); };
  return {
    pause: useMutation({
      mutationFn: (force: boolean) => api.post(`/v1/containers/${cid}/pause`, { force }),
      onMutate: async () => {
        await qc.cancelQueries({ queryKey: keys.container(cid) });
        const prev = qc.getQueryData<Container>(keys.container(cid));
        if (prev) qc.setQueryData(keys.container(cid), { ...prev, status: "pausing" });
        return { prev };
      },
      onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(keys.container(cid), ctx.prev); },
      onSettled: invalidate,
    }),
    resume: useMutation({
      mutationFn: () => api.post(`/v1/containers/${cid}/resume`),
      onMutate: async () => {
        await qc.cancelQueries({ queryKey: keys.container(cid) });
        const prev = qc.getQueryData<Container>(keys.container(cid));
        if (prev) qc.setQueryData(keys.container(cid), { ...prev, status: "resuming" });
        return { prev };
      },
      onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(keys.container(cid), ctx.prev); },
      onSettled: invalidate,
    }),
    recover: useMutation({ mutationFn: () => api.post(`/v1/containers/${cid}/recover`), onSuccess: invalidate }),
    destroy: useMutation({ mutationFn: () => api.post(`/v1/containers/${cid}/destroy`), onSuccess: invalidate }),
    restore: useMutation({ mutationFn: () => api.post(`/v1/containers/${cid}/restore`), onSuccess: invalidate }),
    delete: useMutation({ mutationFn: () => api.del(`/v1/containers/${cid}`), onSuccess: invalidate }),
  };
}

export const useImageTags = () =>
  useQuery({
    queryKey: keys.imageTags,
    queryFn: () => api.get<ImageTagsResponse>("/v1/images/tags"),
  });

export function useUpdateImage(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (image_tag: string) =>
      api.post<{ id: string; status: string; image_tag: string }>(
        `/v1/containers/${cid}/update-image`,
        { image_tag },
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.containers });
      qc.invalidateQueries({ queryKey: keys.container(cid) });
    },
  });
}

export function useUpdateResources(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { mem_limit?: string; cpus?: number }) =>
      api.patch<{ id: string; status: string; mem_limit: string; cpus: number; applied: boolean }>(
        `/v1/containers/${cid}/resources`,
        body,
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.containers });
      qc.invalidateQueries({ queryKey: keys.container(cid) });
    },
  });
}

export function useCreateContainer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string; template_id: string; image_variant: "full" | "slim";
      external_id?: string; config?: AgentConfig;
      resource_limits?: { mem_limit?: string; cpus?: number };
    }) => api.post<Container>("/v1/containers", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.containers }),
  });
}
export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<ApiKeyCreated>("/v1/api-keys", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}
export function useSetCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { provider: string; api_key: string }) => api.post<Credential>("/v1/credentials", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.credentials }),
  });
}

export const useCredentialProviders = () =>
  useQuery({
    queryKey: ["credential-providers"] as const,
    queryFn: () => api.get<{ providers: CredentialProvider[] }>("/v1/credentials/providers"),
  });

export function useStartOpenAIOAuth() {
  return useMutation({
    mutationFn: () =>
      api.post<OAuthStartResponse>("/v1/credentials/oauth/openai/start", {
        tos_acknowledged: true,
      }),
  });
}

export function useStartAnthropicOAuth() {
  return useMutation({
    mutationFn: () =>
      api.post<AnthropicOAuthStart>("/v1/credentials/oauth/anthropic/start", {
        tos_acknowledged: true,
      }),
  });
}

export function useCompleteAnthropicOAuth() {
  return useMutation({
    mutationFn: (b: { connection_id: string; code: string }) =>
      api.post<AnthropicOAuthComplete>("/v1/credentials/oauth/anthropic/complete", b),
  });
}

export const fetchOAuthConnection = (id: string) =>
  api.get<OAuthConnectionStatus>(`/v1/credentials/oauth/openai/connections/${id}`);

export const useModels = (driver: string) =>
  useQuery({
    queryKey: keys.models(driver),
    queryFn: () => api.get<{ models: ModelOption[] }>(`/v1/models?driver=${encodeURIComponent(driver)}`),
    enabled: !!driver,
  });

export const useGitSnapshots = (cid: string) =>
  useQuery({
    queryKey: keys.gitSnapshots(cid),
    queryFn: () => api.get<{ snapshots: GitSnapshot[] }>(`/v1/containers/${cid}/git/snapshots`),
  });

export const useGitRemote = (cid: string, enabled = true) =>
  useQuery({
    queryKey: keys.gitRemote(cid),
    queryFn: () => api.get<{ remote: GitRemote | null }>(`/v1/containers/${cid}/git/remote`),
    enabled,
  });

export function useSaveGitRemote(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { url: string; branch?: string; enabled?: boolean }) =>
      api.put<{ remote: GitRemote }>(`/v1/containers/${cid}/git/remote`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.gitRemote(cid) }),
  });
}

export function useGitRemoteKey(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rotate?: boolean) =>
      api.post<{ public_key: string; fingerprint: string; key_type: string }>(
        `/v1/containers/${cid}/git/remote/key${rotate ? "?rotate=true" : ""}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.gitRemote(cid) }),
  });
}

export function useVerifyGitRemote(cid: string) {
  return useMutation({
    mutationFn: (url: string) =>
      api.post<{ ok: boolean; branches: string[]; default_branch: string | null }>(
        `/v1/containers/${cid}/git/remote/verify`, { url }),
  });
}

export function useUnlinkGitRemote(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del(`/v1/containers/${cid}/git/remote`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.gitRemote(cid) }),
  });
}

// ---- Linked git repo (pull mode) --------------------------------------------
export const useGitLink = (cid: string, enabled = true) =>
  useQuery({
    queryKey: keys.gitLink(cid),
    queryFn: () => api.get<{ linked: LinkedRepo | null }>(`/v1/containers/${cid}/git/link`),
    enabled,
  });

export function useGitLinkKey(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rotate?: boolean) =>
      api.post<{ public_key: string; fingerprint: string; key_type: string }>(
        `/v1/containers/${cid}/git/link/key${rotate ? "?rotate=true" : ""}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.gitLink(cid) }),
  });
}

export function useVerifyGitLink(cid: string) {
  return useMutation({
    mutationFn: (url: string) =>
      api.post<{ ok: boolean; branches: string[]; default_branch: string | null }>(
        `/v1/containers/${cid}/git/link/verify`, { url }),
  });
}

export function useLinkGitRepo(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { url: string; branch: string }) =>
      api.post<{ linked: LinkedRepo }>(`/v1/containers/${cid}/git/link`, { ...body, confirm: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.gitLink(cid) });
      qc.invalidateQueries({ queryKey: keys.container(cid) });
      qc.invalidateQueries({ queryKey: ["containers", cid, "files"] });
    },
  });
}

export function useRepullGitRepo(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ linked: LinkedRepo }>(`/v1/containers/${cid}/git/link/repull`, { confirm: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.gitLink(cid) });
      qc.invalidateQueries({ queryKey: ["containers", cid, "files"] });
    },
  });
}

export function useUnlinkGitRepo(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del(`/v1/containers/${cid}/git/link`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.gitLink(cid) });
      qc.invalidateQueries({ queryKey: keys.container(cid) });
    },
  });
}

export function useGitRollback(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sha: string) => api.post<{ sha: string }>(`/v1/containers/${cid}/git/rollback`, { sha }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.gitSnapshots(cid) });
      qc.invalidateQueries({ queryKey: ["containers", cid, "files"] });
      qc.invalidateQueries({ queryKey: keys.gitRemote(cid) });
    },
  });
}

export function useGitPushNow(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ pushed: boolean; sha: string }>(`/v1/containers/${cid}/git/push`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.gitRemote(cid) }),
  });
}

// ---- Opencode skills --------------------------------------------------------
export const useSkills = () =>
  useQuery({ queryKey: keys.skills, queryFn: () => api.get<{ skills: Skill[] }>("/v1/skills") });

// Single skill incl. body — fetched on demand when editing (the list omits body).
export const fetchSkill = (id: string) => api.get<Skill>(`/v1/skills/${id}`);

// Curated "Awesome SKILL.md" catalog for the New skill "Recommended" tab.
// Fetched client-side from GitHub raw; cached for the session.
export const useRecommendedSkills = () =>
  useQuery({
    queryKey: ["recommended-skills"],
    queryFn: fetchRecommendedSkills,
    staleTime: 1000 * 60 * 30,
    gcTime: 1000 * 60 * 60,
    retry: 1,
  });

type SaveSkillInput =
  | { id?: string; source_type?: "inline"; name: string; description: string; body: string; enabled?: boolean }
  | { id?: string; source_type: "git"; source_url: string; source_subpath: string; source_ref: string; enabled?: boolean };

export function useSaveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: SaveSkillInput & { id?: string }) =>
      id
        ? api.patch<Skill>(`/v1/skills/${id}`, body)
        : api.post<Skill>("/v1/skills", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.skills }),
  });
}

// List a git repo's branches for the create form's branch picker (read-only).
export function useSkillGitRefs() {
  return useMutation({
    mutationFn: (source_url: string) =>
      api.post<{ ok: boolean; branches: string[]; default_branch: string | null }>(
        "/v1/skills/git-refs", { source_url }),
  });
}

export function useRefreshSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Skill>(`/v1/skills/${id}/refresh`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.skills }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/v1/skills/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.skills }),
  });
}

// ---- Deploy keys -------------------------------------------------------------
// SSH keypairs used to grant a skill read-only clone access to a private GitHub
// repo. The API generates the keypair server-side and never returns the private
// half — only the public key + fingerprint come back.
export type DeployKey = {
  id: string; name: string; ssh_public_key: string; key_type: string;
  key_fingerprint: string; created_at: string | null; updated_at: string | null;
};

export function useDeployKeys() {
  return useQuery({
    queryKey: keys.deployKeys,
    queryFn: () => api.get<{ deploy_keys: DeployKey[] }>("/v1/deploy-keys"),
    select: (d) => d.deploy_keys,
  });
}

export function useCreateDeployKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<DeployKey>("/v1/deploy-keys", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.deployKeys }),
  });
}

export function useDeleteDeployKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/v1/deploy-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.deployKeys }),
  });
}

// ---- MCP servers ------------------------------------------------------------
export const useMcpServers = () =>
  useQuery({ queryKey: keys.mcpServers, queryFn: () => api.get<{ mcp_servers: McpServer[] }>("/v1/mcp-servers") });

// Single server — fetched on demand when editing (list and detail both omit the secret).
export const fetchMcpServer = (id: string) => api.get<McpServer>(`/v1/mcp-servers/${id}`);

export type SaveMcpInput = {
  id?: string;
  name: string;
  description: string;
  url: string;
  auth_type: McpAuthType;
  auth_header_name?: string | null;
  secret?: string;       // omit to keep; "" to clear; value to set
  enabled?: boolean;
};

export function useSaveMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: SaveMcpInput) =>
      id
        ? api.patch<McpServer>(`/v1/mcp-servers/${id}`, body)
        : api.post<McpServer>("/v1/mcp-servers", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.mcpServers }),
  });
}

export function useDeleteMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/v1/mcp-servers/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.mcpServers }),
  });
}

// ---- Prompts -----------------------------------------------------------------
// `enabled` lets always-mounted consumers (the PromptPicker) defer the fetch
// until they're actually opened, instead of hitting /v1/prompts on every host mount.
export const usePrompts = (opts?: { enabled?: boolean }) =>
  useQuery({
    queryKey: keys.prompts,
    queryFn: () => api.get<{ prompts: Prompt[] }>("/v1/prompts"),
    enabled: opts?.enabled ?? true,
  });

export const fetchPrompt = (id: string) => api.get<Prompt>(`/v1/prompts/${id}`);

export type SavePromptInput = {
  id?: string;
  name: string;
  body: string;
  tags: string[];
  variables: PromptVariable[];
};

export function useSavePrompt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: SavePromptInput) =>
      id
        ? api.patch<Prompt>(`/v1/prompts/${id}`, body)
        : api.post<Prompt>("/v1/prompts", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.prompts }),
  });
}

export function useDeletePrompt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/v1/prompts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.prompts }),
  });
}

export const useScheduledTasks = () =>
  useQuery({
    queryKey: keys.scheduledTasks(),
    queryFn: () => api.get<{ scheduled_tasks: ScheduledTask[] }>("/v1/scheduled-tasks"),
  });

export const useScheduledTask = (sid: string) =>
  useQuery({
    queryKey: keys.scheduledTask(sid),
    queryFn: () => api.get<ScheduledTask>(`/v1/scheduled-tasks/${sid}`),
    enabled: !!sid,
  });

export function useCreateScheduledTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScheduledTaskCreate) =>
      api.post<ScheduledTask>("/v1/scheduled-tasks", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.scheduledTasks() }),
  });
}

export function useUpdateScheduledTask(sid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScheduledTaskUpdate) =>
      api.patch<ScheduledTask>(`/v1/scheduled-tasks/${sid}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.scheduledTasks() });
      qc.invalidateQueries({ queryKey: keys.scheduledTask(sid) });
    },
  });
}

export function useDeleteScheduledTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sid: string) => api.del(`/v1/scheduled-tasks/${sid}`),
    onSuccess: (_data, sid) => {
      qc.invalidateQueries({ queryKey: keys.scheduledTasks() });
      qc.invalidateQueries({ queryKey: keys.scheduledTask(sid) });
    },
  });
}

// ---- Workflows ---------------------------------------------------------------
export const useWorkflows = (opts?: { enabled?: boolean }) =>
  useQuery({
    queryKey: keys.workflows,
    queryFn: () => api.get<{ workflows: Workflow[] }>("/v1/workflows"),
    enabled: opts?.enabled ?? true,
  });

export const useWorkflow = (wid: string) =>
  useQuery({
    queryKey: keys.workflow(wid),
    queryFn: () => api.get<Workflow>(`/v1/workflows/${wid}`),
    enabled: !!wid,
  });

export const useWorkflowRuns = (wid: string) =>
  useQuery({
    queryKey: keys.workflowRuns(wid),
    queryFn: () => api.get<{ runs: WorkflowRun[] }>(`/v1/workflows/${wid}/runs`),
    enabled: !!wid,
    refetchInterval: 5_000,
  });

export const useWorkflowRun = (wid: string, rid: string | null) =>
  useQuery({
    queryKey: keys.workflowRun(wid, rid ?? ""),
    queryFn: () => api.get<WorkflowRunDetail>(`/v1/workflows/${wid}/runs/${rid}`),
    enabled: !!wid && !!rid,
    refetchInterval: 5_000,
  });

export function useSaveWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: WorkflowCreate & { id?: string }) =>
      id ? api.patch<Workflow>(`/v1/workflows/${id}`, body)
         : api.post<Workflow>("/v1/workflows", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workflows }),
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/v1/workflows/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workflows }),
  });
}

export function useRunWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (wid: string) =>
      api.post<WorkflowRun>(`/v1/workflows/${wid}/run`, { trigger_source: "manual" }),
    onSuccess: (_d, wid) => qc.invalidateQueries({ queryKey: keys.workflowRuns(wid) }),
  });
}
