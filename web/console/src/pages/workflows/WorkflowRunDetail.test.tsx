// web/console/src/pages/workflows/WorkflowRunDetail.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { vi } from "vitest";
import WorkflowRunDetail from "./WorkflowRunDetail";

vi.mock("../../api/queries", () => ({
  useWorkflow: () => ({ data: { id: "wf_1", name: "WF", steps: [
    { prompt_id: "prm_1", container_id: "con_1", variables: {} },
    { prompt_id: "prm_2", container_id: "con_2", variables: {} }] } }),
  useWorkflowRuns: () => ({ data: { runs: [
    { id: "wfr_1", workflow_id: "wf_1", status: "running", cursor: 1, step_count: 2,
      current_task_id: "tsk_2", error_step: null, error_message: null,
      trigger_source: "manual", scheduled_task_id: null, started_at: "", ended_at: null }] } }),
}));

test("shows the current step as running", () => {
  render(<MemoryRouter initialEntries={["/workflows/wf_1"]}>
    <Routes><Route path="/workflows/:id" element={<WorkflowRunDetail />} /></Routes>
  </MemoryRouter>);
  expect(screen.getByText(/step 2 of 2/i)).toBeTruthy();
  expect(screen.getByText(/running/i)).toBeTruthy();
});
