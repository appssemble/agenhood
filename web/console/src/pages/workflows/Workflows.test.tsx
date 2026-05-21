import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, beforeEach } from "vitest";
import Workflows from "./Workflows";

let mockWorkflows: any[] = [];
vi.mock("../../api/queries", () => ({
  useWorkflows: () => ({ data: { workflows: mockWorkflows }, isLoading: false }),
  useDeleteWorkflow: () => ({ mutateAsync: vi.fn() }),
  useRunWorkflow: () => ({ mutateAsync: vi.fn() }),
  usePrompts: () => ({ data: { prompts: [] } }),
  useScheduledTasks: () => ({ data: { scheduled_tasks: [] } }),
}));
vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

beforeEach(() => {
  mockWorkflows = [{ id: "wf_1", name: "Nightly", description: null,
    steps: [{ prompt_id: "prm_1", container_id: "con_1", variables: {} }],
    created_by: null, created_at: "", updated_at: "" }];
});

test("lists workflows with a step count", () => {
  render(<MemoryRouter><Workflows /></MemoryRouter>);
  expect(screen.getByText("Nightly")).toBeTruthy();
  expect(screen.getByText(/1 step/i)).toBeTruthy();
});
