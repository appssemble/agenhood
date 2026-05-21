import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { RunsList } from "./RunsList";
import type { WorkflowRun } from "../../../api/types";

function mk(p: Partial<WorkflowRun>): WorkflowRun {
  return {
    id: "wfr_1", workflow_id: "wf_1", status: "completed", cursor: 1, step_count: 2,
    current_task_id: null, error_step: null, error_message: null,
    trigger_source: "schedule", scheduled_task_id: null,
    started_at: "2026-06-29T09:00:00Z", ended_at: "2026-06-29T09:04:00Z", ...p,
  };
}

describe("RunsList", () => {
  test("empty state shows Run now", () => {
    const onRunNow = vi.fn();
    render(<RunsList runs={[]} selectedRunId={null} onSelect={() => {}} nowMs={0} onRunNow={onRunNow} running={false} />);
    expect(screen.getByText(/No runs yet/i)).toBeInTheDocument();
  });
  test("rows render and select", () => {
    const onSelect = vi.fn();
    const runs = [mk({ id: "wfr_a" }), mk({ id: "wfr_b", status: "failed", error_step: 1 })];
    render(<RunsList runs={runs} selectedRunId="wfr_a" onSelect={onSelect} nowMs={Date.parse("2026-06-29T11:00:00Z")} onRunNow={() => {}} running={false} />);
    expect(screen.getByText("wfr_a")).toBeInTheDocument();
    fireEvent.click(screen.getByText("wfr_b"));
    expect(onSelect).toHaveBeenCalledWith("wfr_b");
  });
  test("shows outcome, trigger and failed-step context", () => {
    const runs = [
      mk({ id: "wfr_a" }),
      mk({ id: "wfr_b", status: "failed", error_step: 1 }),
    ];
    render(<RunsList runs={runs} selectedRunId={null} onSelect={() => {}} nowMs={Date.parse("2026-06-29T11:00:00Z")} onRunNow={() => {}} running={false} />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("at step 2")).toBeInTheDocument(); // failed run's error_step
    expect(screen.getAllByText("Scheduled").length).toBe(2);    // trigger label per row
  });
});
