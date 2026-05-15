import { useState } from "react";
import type { WorkflowStep, Prompt, Container } from "../../api/types";
import { Field } from "../../ui/Field";
import { Dropdown } from "../../ui/Dropdown";
import { Icons } from "../../ui/Icon";
import { InlinePromptEditor } from "./InlinePromptEditor";
import { reconcileStepValues } from "./builderUtils";

const NEW_PROMPT = "__new__";

interface StepRowProps {
  index: number;
  isLast: boolean;
  step: WorkflowStep;
  prompts: Prompt[];
  containers: Container[];
  usageCount: number;
  onChange: (next: WorkflowStep) => void;
  onRemove: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export default function StepRow({
  index, isLast, step, prompts, containers, usageCount, onChange, onRemove, onMoveUp, onMoveDown,
}: StepRowProps) {
  const selectedPrompt = prompts.find((p) => p.id === step.prompt_id);
  const vars = selectedPrompt?.variables ?? [];
  const [editor, setEditor] = useState<null | "edit" | "create">(null);

  function handlePromptPick(value: string) {
    if (value === NEW_PROMPT) { setEditor("create"); return; }
    const newPrompt = prompts.find((p) => p.id === value);
    const newVariables: Record<string, string> = {};
    newPrompt?.variables.forEach((v) => { newVariables[v.name] = ""; });
    onChange({ ...step, prompt_id: value, variables: newVariables });
    setEditor(null);
  }

  function handleVariableChange(name: string, value: string) {
    onChange({ ...step, variables: { ...step.variables, [name]: value } });
  }

  function handlePromptSaved(prompt: Prompt) {
    // Editing the currently-selected shared prompt → reconcile this step's values.
    onChange({ ...step, variables: reconcileStepValues(step.variables, prompt.variables) });
  }

  function handlePromptCreated(prompt: Prompt) {
    // New prompt → select it and seed empty values; the prompts list refreshes via the query.
    onChange({ ...step, prompt_id: prompt.id, variables: reconcileStepValues({}, prompt.variables) });
    setEditor(null);
  }

  const promptOptions = [
    ...prompts.map((p) => ({ value: p.id, label: p.name })),
    { value: NEW_PROMPT, label: "+ New prompt" },
  ];

  return (
    <div className="wfb-step">
      <div className="wfb-rail" data-last={isLast || undefined}>
        <span className="wfb-num">{index + 1}</span>
      </div>

      <div className="wfb-card">
        <div className="wfb-card-head">
          <span className="wfb-card-title">Step {index + 1}</span>
          <div className="wfb-card-actions">
            <button type="button" className="btn btn-ghost btn-icon btn-sm"
              onClick={onMoveUp} disabled={!onMoveUp} aria-label="Move step up"><Icons.ArrowUp w={15} /></button>
            <button type="button" className="btn btn-ghost btn-icon btn-sm"
              onClick={onMoveDown} disabled={!onMoveDown} aria-label="Move step down"><Icons.ArrowDown w={15} /></button>
            <button type="button" className="btn btn-ghost btn-icon btn-sm"
              onClick={onRemove} aria-label="Remove step" style={{ color: "var(--err-500)" }}><Icons.Trash w={15} /></button>
          </div>
        </div>

        <div className="wfb-card-body">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {step.prompt_id && usageCount > 0 && editor !== "create" && (
              <span className={`pill ${usageCount > 1 ? "pill-warn" : "pill-dormant"}`} style={{ fontSize: 10.5 }}>
                used by {usageCount}
              </span>
            )}
            <span className="spacer" />
            <button
              type="button"
              aria-label="Edit prompt"
              className={`wfb-prompt-toggle ${editor === "edit" ? "open" : ""}`.trim()}
              disabled={!step.prompt_id || editor === "create"}
              title={step.prompt_id ? "View / edit this prompt" : "Select a prompt to edit it"}
              onClick={() => setEditor((cur) => (cur === "edit" ? null : "edit"))}
            >
              Edit prompt {editor === "edit" ? <Icons.ArrowDown w={13} /> : <Icons.ArrowRight w={13} />}
            </button>
          </div>

          <div className="wfb-grid2">
            <Field label="Prompt" htmlFor={`step-${index}-prompt`}>
              <Dropdown
                id={`step-${index}-prompt`} aria-label="Prompt" portal placeholder="Select prompt…"
                value={step.prompt_id} onChange={handlePromptPick} options={promptOptions}
              />
            </Field>
            <Field label="Runs on" htmlFor={`step-${index}-container`}>
              <Dropdown
                id={`step-${index}-container`} aria-label="Container" portal placeholder="Select container…"
                value={step.container_id} onChange={(v) => onChange({ ...step, container_id: v })}
                options={containers.map((c) => ({ value: c.id, label: c.name }))}
              />
            </Field>
          </div>

          {vars.length > 0 && (
            <div className="wfb-vars">
              <div className="wfb-vars-lab">Values for this step</div>
              <div className="wfb-vars-grid">
                {vars.map((v) => (
                  <div key={v.name}>
                    <label className="wfb-var-lab" htmlFor={`var-${index}-${v.name}`}>{`{{${v.name}}}`}</label>
                    <input
                      id={`var-${index}-${v.name}`} aria-label={`Variable ${v.name}`} className="input"
                      value={step.variables[v.name] ?? ""}
                      onChange={(e) => handleVariableChange(v.name, e.target.value)}
                      placeholder={v.default || "value"}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {editor === "edit" && selectedPrompt && (
            <InlinePromptEditor
              mode="edit" prompt={selectedPrompt} usageCount={usageCount}
              onSaved={handlePromptSaved} onCancel={() => setEditor(null)}
            />
          )}
          {editor === "create" && (
            <InlinePromptEditor
              mode="create" usageCount={0}
              onSaved={handlePromptCreated} onCancel={() => setEditor(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
