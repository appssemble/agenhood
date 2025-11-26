import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskLimitsFields } from "./TaskLimitsFields";

const base = {
  supportsMaxIterations: true,
  iterDefault: 8,
  tokensDefault: 200000,
  timeoutDefault: 600,
  tenantLimits: {
    default_max_iterations: 20,
    default_max_tokens: 500000,
    default_task_timeout_seconds: 1800,
  } as never,
  setMaxIter: vi.fn(),
  setMaxTokens: vi.fn(),
  setTimeoutS: vi.fn(),
};

describe("TaskLimitsFields — inherit-vs-override placeholders", () => {
  it("blank override shows the container default as placeholder (inherits)", () => {
    render(
      <TaskLimitsFields {...base} maxIter={null} maxTokens={null} timeoutS={null} />,
    );
    expect(screen.getByLabelText("Max iterations")).toHaveAttribute("placeholder", "8");
    expect(screen.getByLabelText("Max tokens")).toHaveAttribute("placeholder", "200000");
    expect(screen.getByLabelText("Timeout (s)")).toHaveAttribute("placeholder", "600");
  });

  it("blank override shows empty value (input is uncontrolled-like, no typed digit)", () => {
    render(
      <TaskLimitsFields {...base} maxIter={null} maxTokens={null} timeoutS={null} />,
    );
    // value={null ?? ""} → value=""
    expect(screen.getByLabelText("Max iterations")).toHaveValue(null);
  });

  it("an explicit override is shown as the input value, not the placeholder", () => {
    render(
      <TaskLimitsFields {...base} maxIter={3} maxTokens={1000} timeoutS={30} />,
    );
    expect(screen.getByLabelText("Max iterations")).toHaveValue(3);
    expect(screen.getByLabelText("Max tokens")).toHaveValue(1000);
    expect(screen.getByLabelText("Timeout (s)")).toHaveValue(30);
  });

  it("placeholder is empty string when iterDefault is null", () => {
    render(
      <TaskLimitsFields
        {...base}
        iterDefault={null}
        maxIter={null}
        maxTokens={null}
        timeoutS={null}
      />,
    );
    expect(screen.getByLabelText("Max iterations")).toHaveAttribute("placeholder", "");
  });
});

describe("TaskLimitsFields — supportsMaxIterations gating", () => {
  it("hides the iterations field when the driver lacks max-iterations support", () => {
    render(
      <TaskLimitsFields
        {...base}
        supportsMaxIterations={false}
        maxIter={null}
        maxTokens={null}
        timeoutS={null}
      />,
    );
    expect(screen.queryByLabelText("Max iterations")).toBeNull();
  });

  it("still shows Max tokens and Timeout when iterations is hidden", () => {
    render(
      <TaskLimitsFields
        {...base}
        supportsMaxIterations={false}
        maxIter={null}
        maxTokens={null}
        timeoutS={null}
      />,
    );
    expect(screen.getByLabelText("Max tokens")).toBeInTheDocument();
    expect(screen.getByLabelText("Timeout (s)")).toBeInTheDocument();
  });

  it("shows the iterations field when supportsMaxIterations=true", () => {
    render(
      <TaskLimitsFields {...base} maxIter={null} maxTokens={null} timeoutS={null} />,
    );
    expect(screen.getByLabelText("Max iterations")).toBeInTheDocument();
  });
});

describe("TaskLimitsFields — setter emissions", () => {
  it("calls setMaxIter with the parsed number on change", async () => {
    const setMaxIter = vi.fn();
    render(
      <TaskLimitsFields
        {...base}
        setMaxIter={setMaxIter}
        maxIter={null}
        maxTokens={null}
        timeoutS={null}
      />,
    );
    const input = screen.getByLabelText("Max iterations");
    await userEvent.type(input, "5");
    expect(setMaxIter).toHaveBeenCalledWith(5);
  });

  it("calls setMaxTokens with the parsed number on change", async () => {
    const setMaxTokens = vi.fn();
    render(
      <TaskLimitsFields
        {...base}
        setMaxTokens={setMaxTokens}
        maxIter={null}
        maxTokens={null}
        timeoutS={null}
      />,
    );
    const input = screen.getByLabelText("Max tokens");
    await userEvent.type(input, "9");
    expect(setMaxTokens).toHaveBeenCalledWith(9);
  });

  it("calls setTimeoutS with null when the field is cleared", async () => {
    const setTimeoutS = vi.fn();
    render(
      <TaskLimitsFields
        {...base}
        setTimeoutS={setTimeoutS}
        maxIter={null}
        maxTokens={null}
        timeoutS={30}
      />,
    );
    const input = screen.getByLabelText("Timeout (s)");
    await userEvent.clear(input);
    expect(setTimeoutS).toHaveBeenCalledWith(null);
  });
});
