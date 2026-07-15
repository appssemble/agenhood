import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// Isolate StepRow from the editor (tested separately) and React Query.
vi.mock("./InlinePromptEditor", () => ({
  InlinePromptEditor: (p: { mode: string }) => <div data-testid="editor">editor:{p.mode}</div>,
}));

import StepRow from "./StepRow";
import type { Prompt, Container, WorkflowStep } from "../../api/types";

const PROMPTS: Prompt[] = [
  { id: "prm_1", name: "Build", body: "Hi {{x}}", tags: [], variables: [{ name: "x", default: "" }], created_by: null, created_at: "", updated_at: "" },
];
const CONTAINERS = [{ id: "con_1", name: "ci" }] as unknown as Container[];

function renderRow(step: WorkflowStep, usageCount = 0, onChange = vi.fn()) {
  render(
    <StepRow index={0} isLast step={step} prompts={PROMPTS} containers={CONTAINERS}
      usageCount={usageCount} onChange={onChange} onRemove={() => {}} />,
  );
  return { onChange };
}

describe("StepRow", () => {
  it("disables Edit prompt until a prompt is selected", () => {
    renderRow({ prompt_id: "", container_id: "", variables: {} });
    expect(screen.getByRole("button", { name: /edit prompt/i })).toBeDisabled();
  });

  it("opens the editor in edit mode and shows the usage chip", () => {
    renderRow({ prompt_id: "prm_1", container_id: "con_1", variables: { x: "v" } }, 3);
    expect(screen.getByText(/used by 3/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /edit prompt/i }));
    expect(screen.getByTestId("editor")).toHaveTextContent("editor:edit");
  });

  it("still renders the step's value input for the selected prompt's variable", () => {
    renderRow({ prompt_id: "prm_1", container_id: "con_1", variables: { x: "v" } });
    expect(screen.getByLabelText("Variable x")).toBeInTheDocument();
  });
});

function renderRowExports(step: WorkflowStep, isLast = false, onChange = vi.fn()) {
  render(
    <StepRow index={0} isLast={isLast} step={step} prompts={PROMPTS} containers={CONTAINERS}
      usageCount={0} onChange={onChange} onRemove={() => {}} />,
  );
  return { onChange };
}

describe("exports editor", () => {
  const base = { prompt_id: "prm_1", container_id: "con_1", variables: {} };

  it("adds an export row", () => {
    const { onChange } = renderRowExports({ ...base });
    fireEvent.click(screen.getByRole("button", { name: /add file/i }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ exports: [""] }));
  });

  it("edits an existing export value", () => {
    const { onChange } = renderRowExports({ ...base, exports: ["dist/**"] });
    fireEvent.change(screen.getByLabelText("Export path 1"), {
      target: { value: "report.pdf" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ exports: ["report.pdf"] }),
    );
  });

  it("removes an export row", () => {
    const { onChange } = renderRowExports({ ...base, exports: ["a.txt", "b.txt"] });
    fireEvent.click(screen.getByRole("button", { name: "Remove export 1" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ exports: ["b.txt"] }),
    );
  });

  it("shows the last-step hint when last with a non-empty export", () => {
    renderRowExports({ ...base, exports: ["a.txt"] }, true);
    expect(screen.getByText(/last step/i)).toBeInTheDocument();
  });

  it("hides the hint when not last", () => {
    renderRowExports({ ...base, exports: ["a.txt"] }, false);
    expect(screen.queryByText(/last step/i)).not.toBeInTheDocument();
  });
});
