import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

vi.mock("../../api/queries", () => ({
  useWorkflow: () => ({ data: {
    id: "wf_1", name: "Release Notes Bot", description: "desc",
    steps: [{ prompt_id: "prm_a", container_id: "con_1", variables: {} }],
    created_by: null, created_at: "", updated_at: "",
  }, isLoading: false, isError: false }),
  useWorkflowRuns: () => ({ data: { runs: [] } }),
  useWorkflowRun: () => ({ data: null }),
  usePrompts: () => ({ data: { prompts: [{ id: "prm_a", name: "Summarize", body: "", tags: [], variables: [], created_by: null, created_at: "", updated_at: "" }] } }),
  useContainers: () => ({ data: { containers: [{ id: "con_1", name: "builder" }] } }),
  useScheduledTasks: () => ({ data: { scheduled_tasks: [] } }),
  useRunWorkflow: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteWorkflow: () => ({ mutateAsync: vi.fn() }),
}));

import { MemoryRouter } from "react-router-dom";
import WorkflowDetail from "./WorkflowDetail";

describe("WorkflowDetail", () => {
  test("renders header, pipeline definition, and empty runs", () => {
    render(
      <MemoryRouter initialEntries={["/workflows/wf_1"]}>
        <WorkflowDetail />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Release Notes Bot" })).toBeInTheDocument();
    expect(screen.getByText("Summarize")).toBeInTheDocument();   // pipeline definition card
    expect(screen.getByText(/No runs yet/i)).toBeInTheDocument();
  });
});
