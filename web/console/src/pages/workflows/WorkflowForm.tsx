import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useSaveWorkflow, useWorkflow, usePrompts, useContainers, useWorkflows } from "../../api/queries";
import { countWorkflowsUsingPrompt } from "./builderUtils";
import { useToast } from "../../components/Toast";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/inputs";
import { CopyId } from "../../ui/CopyId";
import { EmptyState } from "../../ui/EmptyState";
import { Icons } from "../../ui/Icon";
import type { WorkflowStep } from "../../api/types";
import StepRow from "./StepRow";

export default function WorkflowForm() {
  const { id } = useParams();
  const editing = !!id;
  const nav = useNavigate();
  const toast = useToast();
  const save = useSaveWorkflow();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [loaded, setLoaded] = useState(!editing);

  const { data: wf } = useWorkflow(id ?? "");
  const { data: promptsData } = usePrompts();
  const { data: containersData } = useContainers();
  const { data: workflowsData } = useWorkflows();
  const workflows = workflowsData?.workflows ?? [];

  const prompts = promptsData?.prompts ?? [];
  const containers = containersData?.containers ?? [];

  useEffect(() => {
    if (!editing || !wf) return;
    setName(wf.name);
    setDescription(wf.description ?? "");
    setSteps(wf.steps);
    setLoaded(true);
  }, [editing, wf]); // eslint-disable-line react-hooks/exhaustive-deps

  function addStep() {
    setSteps((s) => [...s, { prompt_id: "", container_id: "", variables: {} }]);
  }
  function updateStep(i: number, next: WorkflowStep) {
    setSteps((s) => s.map((step, idx) => (idx === i ? next : step)));
  }
  function removeStep(i: number) {
    setSteps((s) => s.filter((_, idx) => idx !== i));
  }
  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const updated = steps.slice();
    [updated[i], updated[j]] = [updated[j], updated[i]];
    setSteps(updated);
  }

  async function onSave() {
    try {
      await save.mutateAsync({ id, name: name.trim(), description: description.trim() || null, steps });
      toast.success(editing ? "Workflow updated" : "Workflow created");
      nav("/workflows");
    } catch (err) {
      toast.error("Couldn't save workflow", err instanceof ApiError ? err.message : undefined);
    }
  }

  if (!loaded) return <div className="page"><div className="note">Loading…</div></div>;

  const canSave =
    !!name.trim() &&
    steps.length > 0 &&
    steps.every((s) => !!s.prompt_id && !!s.container_id) &&
    !save.isPending;

  const distinctContainers = new Set(steps.map((s) => s.container_id).filter(Boolean)).size;
  const stepsHint =
    steps.length === 0
      ? "Add prompts to run in sequence — each on its own container."
      : `${steps.length} step${steps.length > 1 ? "s" : ""}` +
        (distinctContainers > 0 ? ` · ${distinctContainers} container${distinctContainers > 1 ? "s" : ""}` : "");

  return (
    <div className="page">
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
        <Link to="/workflows" style={{ color: "var(--muted)" }}>Workflows</Link>{" / "}
        {editing ? "Edit" : "New workflow"}
      </div>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 18 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
              {editing ? "Edit workflow" : "New workflow"}
            </div>
            {editing && id && <CopyId id={id} />}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>
            Steps run one after another — the next starts only when the previous finishes.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <Link to="/workflows" className="btn btn-secondary btn-sm">Cancel</Link>
          <Button variant="primary" size="sm" onClick={onSave} disabled={!canSave}>Save workflow</Button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 860 }}>
        <section className="section-card">
          <div className="section-card-head">
            <span className="nc-step">1</span>
            <div className="section-card-titles">
              <span className="section-card-title">Details</span>
              <span className="section-card-hint">Name this workflow and describe what it does.</span>
            </div>
          </div>
          <div className="section-card-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Workflow name" htmlFor="wf-name">
              <Input
                id="wf-name" aria-label="Workflow name" value={name}
                onChange={(e) => setName(e.target.value)} placeholder="e.g. Nightly repo digest"
              />
            </Field>
            <Field label="Description" htmlFor="wf-desc" hint="Optional — shown in the workflow list.">
              <Input
                id="wf-desc" aria-label="Description" value={description}
                onChange={(e) => setDescription(e.target.value)} placeholder="What this workflow does…"
              />
            </Field>
          </div>
        </section>

        <section className="section-card">
          <div className="section-card-head">
            <span className="nc-step">2</span>
            <div className="section-card-titles">
              <span className="section-card-title">Steps</span>
              <span className="section-card-hint">{stepsHint}</span>
            </div>
          </div>
          <div className="section-card-body">
            {prompts.length === 0 ? (
              <EmptyState
                size="sm" icon="Prompt" title="No prompts yet"
                description="Workflows are built from reusable prompts. Create one first."
                actions={<Link to="/prompts/new" className="btn btn-primary btn-sm">New prompt</Link>}
              />
            ) : steps.length === 0 ? (
              <EmptyState
                size="sm" icon="Workflow" title="No steps yet"
                description="Add your first step to start building the sequence."
                actions={
                  <Button variant="primary" size="sm" onClick={addStep} style={{ gap: 6 }}>
                    <Icons.Plus w={14} /> Add step
                  </Button>
                }
              />
            ) : (
              <>
                <div className="wfb-steps">
                  {steps.map((step, i) => (
                    <StepRow
                      key={i}
                      index={i}
                      isLast={i === steps.length - 1}
                      step={step}
                      prompts={prompts}
                      containers={containers}
                      usageCount={countWorkflowsUsingPrompt(workflows, step.prompt_id)}
                      onChange={(next) => updateStep(i, next)}
                      onRemove={() => removeStep(i)}
                      onMoveUp={i > 0 ? () => moveStep(i, -1) : undefined}
                      onMoveDown={i < steps.length - 1 ? () => moveStep(i, 1) : undefined}
                    />
                  ))}
                </div>
                <button type="button" className="wfb-add" onClick={addStep}>
                  <Icons.Plus w={15} /> Add step
                </button>
              </>
            )}

            {prompts.length > 0 && containers.length === 0 && (
              <div className="note" style={{ marginTop: 12 }}>
                You'll need a container to run steps on. <Link to="/containers/new">Create one</Link>.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
