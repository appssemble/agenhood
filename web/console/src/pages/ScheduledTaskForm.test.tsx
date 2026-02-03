import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import ScheduledTaskForm from "./ScheduledTaskForm";

// Mocked data
const mockWorkflows = [
  { id: "w1", name: "My Workflow", description: null, steps: [], created_by: null, created_at: "", updated_at: "" },
];
const mockPrompts = [
  { id: "p1", name: "My Prompt", body: "Hello", tags: [], variables: [], created_by: null, created_at: "", updated_at: "" },
];
const mockContainers = [
  { id: "c1", name: "Container 1", status: "running", external_id: null, image_variant: "full", image_tag: "latest", config: { driver: "vanilla", model: "", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } }, metadata: {}, last_task_at: null, created_at: "", error_message: null },
];

vi.mock("../api/queries", () => ({
  useScheduledTask: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateScheduledTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateScheduledTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useContainers: () => ({ data: { containers: mockContainers }, isLoading: false }),
  usePrompts: () => ({ data: { prompts: mockPrompts }, isLoading: false }),
  useWorkflows: () => ({ data: { workflows: mockWorkflows }, isLoading: false }),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

function renderForm(path = "/schedules/new") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ScheduledTaskForm />
    </MemoryRouter>,
  );
}

describe("ScheduledTaskForm", () => {
  it("renders prompt target by default", () => {
    renderForm();
    // Prompt dropdown (shared Dropdown trigger) is visible in the default state.
    expect(screen.getByLabelText("Prompt")).toBeInTheDocument();
  });

  it("switching to Workflow reveals a workflow dropdown", () => {
    renderForm();

    // Initially no workflow dropdown
    expect(screen.queryByLabelText("Workflow")).not.toBeInTheDocument();

    // Click the Workflow SegControl segment (only button named "Workflow" in prompt mode).
    fireEvent.click(screen.getByRole("button", { name: "Workflow" }));

    // Workflow dropdown should now appear; prompt dropdown should disappear.
    expect(screen.getByLabelText("Workflow")).toBeInTheDocument();
    expect(screen.queryByLabelText("Prompt")).not.toBeInTheDocument();
  });

  it("prefills workflow dropdown when ?kind=workflow&workflow_id= is set", () => {
    renderForm("/schedules/new?kind=workflow&workflow_id=w1");

    // Should start in workflow mode with the selected workflow's name on the trigger.
    const workflowTrigger = screen.getByLabelText("Workflow");
    expect(workflowTrigger).toBeInTheDocument();
    expect(workflowTrigger).toHaveTextContent("My Workflow");
  });
});
