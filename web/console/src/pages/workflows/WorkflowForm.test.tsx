import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import WorkflowForm from "./WorkflowForm";

const save = vi.fn().mockResolvedValue({ id: "wf_1" });
vi.mock("../../api/queries", () => ({
  useSaveWorkflow: () => ({ mutateAsync: save }),
  useWorkflow: () => ({ data: undefined }),
  usePrompts: () => ({ data: { prompts: [
    { id: "prm_1", name: "Build", body: "Hi {{x}}", tags: [], variables: [{ name: "x", default: "" }], created_by: null, created_at: "", updated_at: "" }] } }),
  useContainers: () => ({ data: { containers: [{ id: "con_1", name: "ci" }] } }),
  useWorkflows: () => ({ data: { workflows: [] } }),
}));
vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

test("requires at least one valid step before saving", async () => {
  render(<MemoryRouter><WorkflowForm /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/workflow name/i), { target: { value: "WF" } });
  // No step added yet → Save disabled or shows validation
  expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
});

test("adding a step reveals its prompt/container dropdowns and prompt variables", () => {
  render(<MemoryRouter><WorkflowForm /></MemoryRouter>);
  // Empty state CTA adds the first step.
  fireEvent.click(screen.getByRole("button", { name: /add step/i }));
  expect(screen.getByText("Step 1")).toBeTruthy();

  // Both targets render as the shared custom Dropdown (a labelled trigger button).
  const promptTrigger = screen.getByLabelText("Prompt");
  expect(screen.getByLabelText("Container")).toBeTruthy();

  // Open the prompt dropdown and pick "Build" (options choose on mousedown).
  fireEvent.click(promptTrigger);
  fireEvent.mouseDown(screen.getByRole("option", { name: "Build" }));

  // Selecting the prompt surfaces its {{x}} variable input.
  expect(screen.getByLabelText("Variable x")).toBeTruthy();
});

test("strips empty export entries from the save payload", async () => {
  save.mockClear();
  render(<MemoryRouter><WorkflowForm /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/workflow name/i), { target: { value: "WF" } });
  fireEvent.click(screen.getByRole("button", { name: /add step/i }));
  fireEvent.click(screen.getByLabelText("Prompt"));
  fireEvent.mouseDown(screen.getByRole("option", { name: "Build" }));
  fireEvent.click(screen.getByLabelText("Container"));
  fireEvent.mouseDown(screen.getByRole("option", { name: "ci" }));

  fireEvent.click(screen.getByRole("button", { name: /add file/i }));
  fireEvent.change(screen.getByLabelText("Export path 1"), {
    target: { value: "  report.pdf  " },
  });
  fireEvent.click(screen.getByRole("button", { name: /add file/i })); // second row stays empty

  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  await vi.waitFor(() => expect(save).toHaveBeenCalled());
  const payload = save.mock.calls[save.mock.calls.length - 1][0];
  expect(payload.steps[0].exports).toEqual(["report.pdf"]);
});
