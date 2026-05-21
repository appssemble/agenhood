import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useWorkflows, useDeleteWorkflow, useRunWorkflow, usePrompts, useScheduledTasks } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Icons } from "../../ui/Icon";
import { EmptyState } from "../../ui/EmptyState";
import { scheduleParts } from "../../lib/scheduleSummary";
import type { Workflow } from "../../api/types";

export default function Workflows() {
  const { data, isLoading } = useWorkflows();
  const del = useDeleteWorkflow();
  const run = useRunWorkflow();
  const toast = useToast();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState<Workflow | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const workflows = data?.workflows ?? [];
  const prompts = usePrompts().data?.prompts ?? [];
  const schedules = useScheduledTasks().data?.scheduled_tasks ?? [];

  const promptName = (id: string) => prompts.find((p) => p.id === id)?.name ?? id;
  const scheduleFor = (wid: string) =>
    schedules.find((s) => s.target.kind === "workflow" && s.target.workflow_id === wid);

  async function onDelete(wf: Workflow) {
    try {
      await del.mutateAsync(wf.id);
      toast.success(`Deleted ${wf.name}`);
      setDeleting(null);
    } catch (err) {
      toast.error("Couldn't delete workflow", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onRun(wf: Workflow) {
    setRunning(wf.id);
    try {
      await run.mutateAsync(wf.id);
      toast.success(`Started ${wf.name}`);
      navigate(`/workflows/${wf.id}`);
    } catch (err) {
      toast.error("Couldn't run workflow", err instanceof ApiError ? err.message : undefined);
    } finally {
      setRunning(null);
    }
  }

  function renderCard(wf: Workflow) {
    const stepCount = wf.steps.length;
    const containerCount = new Set(wf.steps.map((s) => s.container_id)).size;
    const sched = scheduleFor(wf.id);

    return (
      <div key={wf.id} className="card wf-card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        {/* Stretched link: makes the whole card open the details (keyboard-accessible),
            while .wf-card-actions sits above it and stays clickable. */}
        <Link to={`/workflows/${wf.id}`} className="wf-card-link" aria-label={`Open ${wf.name}`} />

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: "var(--p-100)", border: "1px solid rgba(135,130,13,.2)", display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Icons.Checklist w={16} />
          </div>
          <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
            {wf.name}
          </div>
          {sched && (
            <span className="pill pill-brand" style={{ fontSize: 9.5, padding: "2px 8px", flexShrink: 0 }}>
              <Icons.Clock w={10} /> {scheduleParts(sched.schedule, sched.timezone).cadence}
            </span>
          )}
        </div>

        {wf.description && (
          <div className="clamp-2" style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.5 }}>
            {wf.description}
          </div>
        )}

        {/* step sequence — numbered node-pills; wraps so every step stays visible */}
        {stepCount > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, minWidth: 0 }}>
            {wf.steps.map((s, i) => (
              <span key={i} title={promptName(s.prompt_id)} style={{ display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%", background: "var(--surface-2)", borderRadius: 999, padding: "3px 9px 3px 3px", minWidth: 0 }}>
                <span style={{ width: 16, height: 16, borderRadius: "50%", background: "var(--ink)", color: "var(--p-300)", fontSize: 9, fontWeight: 800, display: "grid", placeItems: "center", flexShrink: 0 }}>{i + 1}</span>
                <span style={{ fontSize: 11, color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{promptName(s.prompt_id)}</span>
              </span>
            ))}
          </div>
        )}

        {/* meta */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)", marginTop: "auto" }}>
          <Icons.Checklist w={12} />
          <span>{stepCount} step{stepCount === 1 ? "" : "s"}</span>
          {containerCount > 0 && <span style={{ color: "var(--muted-2)" }}>· {containerCount} container{containerCount === 1 ? "" : "s"}</span>}
        </div>

        <div className="wf-card-actions card-actions">
          <Button variant="ghost" size="sm" aria-label={`Run ${wf.name}`} disabled={running === wf.id} onClick={() => onRun(wf)}>
            <Icons.Play w={14} /> Run
          </Button>
          <Link to={`/workflows/${wf.id}/edit`} className="btn btn-ghost btn-sm"><Icons.Pencil w={14} /> Edit</Link>
          <Link to={`/schedules/new?kind=workflow&workflow_id=${wf.id}`} className="btn btn-ghost btn-sm"><Icons.Clock w={14} /> Schedule</Link>
          <Button variant="danger" size="sm" className="danger-sep" aria-label={`Delete ${wf.name}`} onClick={() => setDeleting(wf)}>
            <Icons.Trash w={14} /> Delete
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Workflows</div>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              Multi-step automated sequences. Run prompts across containers in order.
            </div>
          </div>
          {!isLoading && workflows.length > 0 && (
            <Link to="/workflows/new" className="btn btn-primary btn-sm" style={{ gap: 6, padding: "6px 12px 6px 10px" }}>
              <Icons.Plus w={14} /> New workflow
            </Link>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="note">Loading…</div>
      ) : workflows.length === 0 ? (
        <EmptyState
          icon="Checklist"
          title="No workflows yet"
          description="Create a workflow to chain prompts across containers in sequence."
          actions={<Link to="/workflows/new" className="btn btn-primary btn-sm"><Icons.Plus w={14} /> New workflow</Link>}
        />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {workflows.map(renderCard)}
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete workflow"
        body={`Delete "${deleting?.name}"? This can't be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleting && onDelete(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
