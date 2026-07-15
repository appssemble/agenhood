import type {
  Container, Prompt, Workflow, WorkflowRun, WorkflowRunDetail,
} from "../../../api/types";
import { resolve } from "../../../lib/prompts";

export type StepUiStatus = "pending" | "running" | "completed" | "failed";

export const STEP_PILL_TONE: Record<StepUiStatus, "success" | "running" | "dormant" | "error"> = {
  completed: "success",
  running: "running",
  pending: "dormant",
  failed: "error",
};

export const STEP_BADGE_COLOR: Record<StepUiStatus, string> = {
  completed: "var(--success-500)",
  running: "var(--info-500)",
  pending: "var(--border-strong)",
  failed: "var(--err-500)",
};

export function stepStatusFromRun(run: WorkflowRun, i: number): StepUiStatus {
  if (run.status === "failed" && i === run.error_step) return "failed";
  if (i < run.cursor) return "completed";
  if (i === run.cursor) {
    if (run.status === "completed") return "completed";
    if (run.status === "failed") return "failed";
    return "running";
  }
  return "pending";
}

export function runMetrics(runs: WorkflowRun[]) {
  const completed = runs.filter((r) => r.status === "completed").length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const denom = completed + failed;
  const durations = runs
    .filter((r) => r.status === "completed" && r.started_at && r.ended_at)
    .map((r) => Date.parse(r.ended_at as string) - Date.parse(r.started_at as string))
    .filter((d) => Number.isFinite(d) && d >= 0);
  const avg = durations.length
    ? durations.reduce((a, b) => a + b, 0) / durations.length
    : null;
  return {
    total: runs.length,
    completed,
    failed,
    successRate: denom ? completed / denom : null,
    avgDurationMs: avg,
  };
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let u = -1;
  do {
    v /= 1024;
    u += 1;
  } while (v >= 1024 && u < units.length - 1);
  return `${v.toFixed(1)} ${units[u]}`;
}

export function timeAgo(iso: string | null, nowMs: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const s = Math.floor((nowMs - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function resolveStepBody(
  prompt: Prompt | undefined,
  stepVariables: Record<string, string>,
): string {
  if (!prompt) return "";
  const effective: Record<string, string> = {};
  for (const v of prompt.variables ?? []) effective[v.name] = v.default ?? "";
  for (const [k, val] of Object.entries(stepVariables ?? {})) effective[k] = val;
  return resolve(prompt.body, effective);
}

// ---- view models ------------------------------------------------------------

export interface PipelineStepVM {
  index: number;
  promptName: string;
  promptId: string;
  containerName: string;
  varCount: number;
  status: StepUiStatus | null; // null = definition view (no run selected)
  durationLabel: string | null;
}

export interface StepDetailVM {
  index: number;
  promptName: string;
  promptId: string;
  containerName: string;
  containerId: string;
  status: StepUiStatus | null;
  startedAt: string | null;
  durationLabel: string | null;
  taskLink: string | null;
  variables: Array<[string, string]>;
  exports: string[];
  resolvedBody: string;
  errorMessage: string | null;
  transferLabel: string | null;
}

function nameOfPrompt(prompts: Prompt[], id: string): string {
  return prompts.find((p) => p.id === id)?.name ?? id;
}
function nameOfContainer(containers: Container[], id: string): string {
  return containers.find((c) => c.id === id)?.name ?? id;
}

function durationLabelFor(
  tlStatus: StepUiStatus | null,
  startedAt: string | null,
  endedAt: string | null,
  nowMs: number,
): string | null {
  if (!startedAt) return null;
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return null;
  if (endedAt) {
    const end = Date.parse(endedAt);
    if (!Number.isNaN(end)) return formatDuration(end - start);
  }
  if (tlStatus === "running") return formatDuration(nowMs - start);
  return null;
}

interface BuildArgs {
  workflow: Workflow;
  detail: WorkflowRunDetail | null;
  prompts: Prompt[];
  containers: Container[];
  nowMs: number;
}

export function buildPipelineVMs(args: BuildArgs): PipelineStepVM[] {
  const { workflow, detail, prompts, containers, nowMs } = args;
  return workflow.steps.map((step, i) => {
    const tl = detail?.steps?.[i] ?? null;
    let status: StepUiStatus | null = null;
    let durationLabel: string | null = null;
    if (detail) {
      status = tl ? tl.status : stepStatusFromRun(detail, i);
      durationLabel = tl
        ? durationLabelFor(tl.status, tl.started_at, tl.ended_at, nowMs)
        : null;
    }
    return {
      index: i,
      promptName: nameOfPrompt(prompts, step.prompt_id),
      promptId: step.prompt_id,
      containerName: nameOfContainer(containers, step.container_id),
      varCount: Object.keys(step.variables ?? {}).length,
      status,
      durationLabel,
    };
  });
}

export function buildStepDetailVM(
  args: BuildArgs & { index: number },
): StepDetailVM {
  const { workflow, detail, prompts, containers, nowMs, index } = args;
  const step = workflow.steps[index];
  const prompt = prompts.find((p) => p.id === step.prompt_id);
  const tl = detail?.steps?.[index] ?? null;
  const status: StepUiStatus | null = detail
    ? tl
      ? tl.status
      : stepStatusFromRun(detail, index)
    : null;
  const taskId = tl?.task_id ?? null;
  const taskContainerId = tl?.container_id ?? step.container_id;
  const taskLink =
    taskId && taskContainerId
      ? `/containers/${taskContainerId}/tasks/${taskId}`
      : null;
  const isFailedStep =
    !!detail && detail.status === "failed" && detail.error_step === index;
  const transfer = tl?.transfer ?? null;
  const transferLabel = transfer
    ? `${transfer.files} file${transfer.files === 1 ? "" : "s"} · ${formatBytes(transfer.bytes)} → step ${index + 2}`
    : null;
  return {
    index,
    promptName: nameOfPrompt(prompts, step.prompt_id),
    promptId: step.prompt_id,
    containerName: nameOfContainer(containers, step.container_id),
    containerId: step.container_id,
    status,
    startedAt: tl?.started_at ?? null,
    durationLabel: tl
      ? durationLabelFor(tl.status, tl.started_at, tl.ended_at, nowMs)
      : null,
    taskLink,
    variables: Object.entries(step.variables ?? {}),
    exports: step.exports ?? [],
    resolvedBody: resolveStepBody(prompt, step.variables ?? {}),
    errorMessage: isFailedStep ? detail!.error_message : null,
    transferLabel,
  };
}
