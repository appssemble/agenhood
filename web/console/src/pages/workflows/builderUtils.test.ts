import { describe, it, expect } from "vitest";
import { reconcileStepValues, countWorkflowsUsingPrompt, buildPromptVariables } from "./builderUtils";
import type { Workflow, PromptVariable } from "../../api/types";

describe("reconcileStepValues", () => {
  it("preserves existing, adds new empty, drops removed", () => {
    const vars: PromptVariable[] = [{ name: "tone" }, { name: "lang" }];
    expect(reconcileStepValues({ tone: "friendly", gone: "x" }, vars)).toEqual({ tone: "friendly", lang: "" });
  });
  it("empty when no variables", () => {
    expect(reconcileStepValues({ a: "1" }, [])).toEqual({});
  });
});

describe("countWorkflowsUsingPrompt", () => {
  const wf = (id: string, promptIds: string[]): Workflow => ({
    id, name: id, description: null,
    steps: promptIds.map((p) => ({ prompt_id: p, container_id: "c", variables: {} })),
    created_by: null, created_at: "", updated_at: "",
  });
  it("counts workflows referencing the prompt", () => {
    const wfs = [wf("a", ["prm_1", "prm_2"]), wf("b", ["prm_2"]), wf("c", ["prm_3"])];
    expect(countWorkflowsUsingPrompt(wfs, "prm_2")).toBe(2);
    expect(countWorkflowsUsingPrompt(wfs, "prm_1")).toBe(1);
    expect(countWorkflowsUsingPrompt(wfs, "")).toBe(0);
  });
});

describe("buildPromptVariables", () => {
  it("maps names to {name,label,default} from meta", () => {
    expect(buildPromptVariables(["tone"], { tone: { label: "Tone", default: "neutral" } }))
      .toEqual([{ name: "tone", label: "Tone", default: "neutral" }]);
    expect(buildPromptVariables(["x"], {})).toEqual([{ name: "x", label: "", default: "" }]);
  });
});
