import { render, screen, fireEvent } from "@testing-library/react";
import { vi, beforeEach } from "vitest";
import { PromptPicker } from "./PromptPicker";

// Mutable fixture — tests override this before render to control what usePrompts returns.
let mockPrompts: any[] = [];

vi.mock("../api/queries", () => ({
  usePrompts: () => ({
    data: { prompts: mockPrompts },
    isLoading: false,
  }),
}));

beforeEach(() => {
  mockPrompts = [
    { id: "prm_1", name: "Weekly", body: "Hi {{team}}",
      tags: [], variables: [{ name: "team", label: "Team", default: "" }],
      created_by: null, created_at: "", updated_at: "" },
    { id: "prm_2", name: "NoVars", body: "Just text",
      tags: [], variables: [], created_by: null, created_at: "", updated_at: "" },
  ];
});

test("fills a variable and inserts the resolved text", () => {
  const onInsert = vi.fn();
  render(<PromptPicker open onInsert={onInsert} onClose={() => {}} />);
  // First prompt is auto-selected; fill its variable.
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: "Platform" } });
  fireEvent.click(screen.getByRole("button", { name: /insert/i }));
  expect(onInsert).toHaveBeenCalledWith("Hi Platform");
});

test("inserts immediately for a prompt with no variables", () => {
  const onInsert = vi.fn();
  render(<PromptPicker open onInsert={onInsert} onClose={() => {}} />);
  fireEvent.click(screen.getByText("NoVars"));
  fireEvent.click(screen.getByRole("button", { name: /insert/i }));
  expect(onInsert).toHaveBeenCalledWith("Just text");
});

test("auto-selected prompt resolves variable defaults without user input", () => {
  // Override fixture: first (auto-selected) prompt has a non-empty default.
  mockPrompts = [
    { id: "prm_3", name: "DefaultTest", body: "Hi {{team}}",
      tags: [], variables: [{ name: "team", label: "Team", default: "Platform" }],
      created_by: null, created_at: "", updated_at: "" },
  ];
  const onInsert = vi.fn();
  render(<PromptPicker open onInsert={onInsert} onClose={() => {}} />);
  // Do NOT click any prompt or fill any input — rely on auto-selection + effectiveValues defaults.
  fireEvent.click(screen.getByRole("button", { name: /insert/i }));
  expect(onInsert).toHaveBeenCalledWith("Hi Platform");
});
