import type { PromptVariable, Workflow } from "../../api/types";

export type VarMeta = { label: string; default: string };

/** Reconcile a step's variable VALUES to a prompt's current variable set:
 *  keep existing values, add new variables as "", drop removed ones. */
export function reconcileStepValues(
  prev: Record<string, string>,
  variables: PromptVariable[],
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const v of variables) next[v.name] = prev[v.name] ?? "";
  return next;
}

/** How many workflows reference this prompt id (the shared-edit blast radius). */
export function countWorkflowsUsingPrompt(workflows: Workflow[], promptId: string): number {
  if (!promptId) return 0;
  return workflows.filter((w) => w.steps.some((s) => s.prompt_id === promptId)).length;
}

/** Build the prompt's PromptVariable[] from detected names + label/default meta. */
export function buildPromptVariables(
  varNames: string[],
  meta: Record<string, VarMeta>,
): PromptVariable[] {
  return varNames.map((n) => ({ name: n, label: meta[n]?.label || "", default: meta[n]?.default || "" }));
}
