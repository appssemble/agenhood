import { describe, expect, test } from "vitest";
import {
  stepStatusFromRun, runMetrics, formatDuration, timeAgo,
  resolveStepBody, buildPipelineVMs, buildStepDetailVM, formatBytes,
} from "./derive";
import type { WorkflowRun, WorkflowRunDetail, Prompt, Container, Workflow } from "../../../api/types";

function run(p: Partial<WorkflowRun>): WorkflowRun {
  return {
    id: "wfr_1", workflow_id: "wf_1", status: "running", cursor: 0, step_count: 3,
    current_task_id: null, error_step: null, error_message: null,
    trigger_source: "manual", scheduled_task_id: null,
    started_at: "2026-06-29T09:00:00Z", ended_at: null, ...p,
  };
}

describe("stepStatusFromRun", () => {
  test("done before cursor, running at cursor, pending after", () => {
    const r = run({ cursor: 1, status: "running" });
    expect(stepStatusFromRun(r, 0)).toBe("completed");
    expect(stepStatusFromRun(r, 1)).toBe("running");
    expect(stepStatusFromRun(r, 2)).toBe("pending");
  });
  test("failed step flagged via error_step", () => {
    const r = run({ cursor: 2, status: "failed", error_step: 2 });
    expect(stepStatusFromRun(r, 2)).toBe("failed");
  });
  test("last step completed", () => {
    const r = run({ cursor: 2, status: "completed" });
    expect(stepStatusFromRun(r, 2)).toBe("completed");
  });
});

describe("runMetrics", () => {
  test("success rate and avg duration over completed", () => {
    const m = runMetrics([
      run({ status: "completed", started_at: "2026-06-29T09:00:00Z", ended_at: "2026-06-29T09:01:00Z" }),
      run({ status: "failed" }),
      run({ status: "running" }),
    ]);
    expect(m.completed).toBe(1);
    expect(m.failed).toBe(1);
    expect(m.successRate).toBeCloseTo(0.5);
    expect(m.avgDurationMs).toBe(60_000);
  });
  test("null rate/avg when no terminal runs", () => {
    const m = runMetrics([run({ status: "running" })]);
    expect(m.successRate).toBeNull();
    expect(m.avgDurationMs).toBeNull();
  });
});

describe("formatDuration", () => {
  test("formats s / m s / h m", () => {
    expect(formatDuration(48_000)).toBe("48s");
    expect(formatDuration(120_000)).toBe("2m");
    expect(formatDuration(252_000)).toBe("4m 12s");
    expect(formatDuration(3_600_000)).toBe("1h");
    expect(formatDuration(-5)).toBe("—");
  });
});

describe("timeAgo", () => {
  test("relative buckets", () => {
    const now = Date.parse("2026-06-29T12:00:00Z");
    expect(timeAgo("2026-06-29T11:59:30Z", now)).toBe("just now");
    expect(timeAgo("2026-06-29T11:30:00Z", now)).toBe("30m ago");
    expect(timeAgo("2026-06-29T10:00:00Z", now)).toBe("2h ago");
    expect(timeAgo("2026-06-27T12:00:00Z", now)).toBe("2d ago");
    expect(timeAgo(null, now)).toBe("—");
  });
});

describe("resolveStepBody", () => {
  test("step value overrides default, empty falls back verbatim", () => {
    const prompt: Prompt = {
      id: "prm_a", name: "P", body: "Tone: {{tone}} / {{missing}}",
      tags: [], variables: [{ name: "tone", default: "neutral" }],
      created_by: null, created_at: "", updated_at: "",
    };
    expect(resolveStepBody(prompt, { tone: "friendly" })).toBe("Tone: friendly / {{missing}}");
    expect(resolveStepBody(prompt, {})).toBe("Tone: neutral / {{missing}}");
    expect(resolveStepBody(prompt, { tone: "" })).toBe("Tone: {{tone}} / {{missing}}");
  });
});

const WF: Workflow = {
  id: "wf_1", name: "WF", description: null,
  steps: [
    { prompt_id: "prm_a", container_id: "con_1", variables: { tone: "friendly" } },
    { prompt_id: "prm_b", container_id: "con_2", variables: {} },
  ],
  created_by: null, created_at: "", updated_at: "",
};
const PROMPTS: Prompt[] = [
  { id: "prm_a", name: "Summarize", body: "{{tone}}", tags: [], variables: [{ name: "tone" }], created_by: null, created_at: "", updated_at: "" },
  { id: "prm_b", name: "Post", body: "x", tags: [], variables: [], created_by: null, created_at: "", updated_at: "" },
];
const CONTAINERS = [
  { id: "con_1", name: "builder" }, { id: "con_2", name: "writer" },
] as unknown as Container[];

describe("buildPipelineVMs", () => {
  test("definition view: neutral status when no run", () => {
    const vms = buildPipelineVMs({ workflow: WF, detail: null, prompts: PROMPTS, containers: CONTAINERS, nowMs: 0 });
    expect(vms.map(v => v.status)).toEqual([null, null]);
    expect(vms[0].promptName).toBe("Summarize");
    expect(vms[0].containerName).toBe("builder");
    expect(vms[0].varCount).toBe(1);
  });
  test("timeline view: status + duration from timeline", () => {
    const detail: WorkflowRunDetail = {
      ...run({ cursor: 1, status: "running" }),
      steps: [
        { step_index: 0, task_id: "tsk_0", container_id: "con_1", status: "completed", started_at: "2026-06-29T09:00:00Z", ended_at: "2026-06-29T09:00:48Z" },
        { step_index: 1, task_id: "tsk_1", container_id: "con_2", status: "running", started_at: "2026-06-29T09:00:48Z", ended_at: null },
      ],
    };
    const vms = buildPipelineVMs({ workflow: WF, detail, prompts: PROMPTS, containers: CONTAINERS, nowMs: Date.parse("2026-06-29T09:01:48Z") });
    expect(vms[0].status).toBe("completed");
    expect(vms[0].durationLabel).toBe("48s");
    expect(vms[1].status).toBe("running");
    expect(vms[1].durationLabel).toBe("1m");  // live elapsed
  });
  test("legacy view: cursor-derived status, no duration when steps null", () => {
    const detail = { ...run({ cursor: 1, status: "running" }), steps: null } as any;
    const vms = buildPipelineVMs({ workflow: WF, detail, prompts: PROMPTS, containers: CONTAINERS, nowMs: 0 });
    expect(vms[0].status).toBe("completed");
    expect(vms[0].durationLabel).toBeNull();
    expect(vms[1].status).toBe("running");
    expect(vms[1].durationLabel).toBeNull();
  });
});

describe("buildStepDetailVM", () => {
  test("builds task link + resolved body + variables", () => {
    const detail: WorkflowRunDetail = {
      ...run({ cursor: 0 }),
      steps: [{ step_index: 0, task_id: "tsk_0", container_id: "con_1", status: "completed", started_at: "2026-06-29T09:00:00Z", ended_at: "2026-06-29T09:00:48Z" }, { step_index: 1, task_id: null, container_id: "con_2", status: "pending", started_at: null, ended_at: null }],
    };
    const vm = buildStepDetailVM({ workflow: WF, detail, prompts: PROMPTS, containers: CONTAINERS, index: 0, nowMs: 0 });
    expect(vm.taskLink).toBe("/containers/con_1/tasks/tsk_0");
    expect(vm.resolvedBody).toBe("friendly");
    expect(vm.variables).toEqual([["tone", "friendly"]]);
    expect(vm.durationLabel).toBe("48s");
  });
  test("no task link when step has no task", () => {
    const detail: WorkflowRunDetail = { ...run({}), steps: null };
    const vm = buildStepDetailVM({ workflow: WF, detail, prompts: PROMPTS, containers: CONTAINERS, index: 1, nowMs: 0 });
    expect(vm.taskLink).toBeNull();
  });
  test("definition view (no run): null status and no task link", () => {
    const vm = buildStepDetailVM({ workflow: WF, detail: null, prompts: PROMPTS, containers: CONTAINERS, index: 0, nowMs: 0 });
    expect(vm.status).toBeNull();
    expect(vm.taskLink).toBeNull();
  });
});

describe("formatBytes", () => {
  test("formats byte counts humanely", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(13002342)).toBe("12.4 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
    expect(formatBytes(-1)).toBe("—");
  });
});

describe("step transfer label", () => {
  const wf: Workflow = {
    id: "wf_1", name: "wf", description: null,
    steps: [
      { prompt_id: "prm_1", container_id: "con_1", variables: {}, exports: ["out/**"] },
      { prompt_id: "prm_1", container_id: "con_2", variables: {} },
    ],
    created_by: null, created_at: "", updated_at: "",
  };
  const detail: WorkflowRunDetail = {
    ...run({ status: "completed", cursor: 1, step_count: 2 }),
    steps: [
      { step_index: 0, task_id: "tsk_1", container_id: "con_1", status: "completed",
        started_at: null, ended_at: null, transfer: { files: 3, bytes: 13002342 } },
      { step_index: 1, task_id: "tsk_2", container_id: "con_2", status: "completed",
        started_at: null, ended_at: null },
    ],
  };
  const args = {
    workflow: wf, detail,
    prompts: [] as Prompt[], containers: [] as Container[], nowMs: 0,
  };

  test("exposes a transfer label when the timeline entry has one", () => {
    expect(buildStepDetailVM({ ...args, index: 0 }).transferLabel)
      .toBe("3 files · 12.4 MB → step 2");
  });

  test("is null without a transfer", () => {
    expect(buildStepDetailVM({ ...args, index: 1 }).transferLabel).toBeNull();
  });
});
