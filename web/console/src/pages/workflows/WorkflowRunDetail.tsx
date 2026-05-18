import { useParams, Link } from "react-router-dom";
import { useWorkflow, useWorkflowRuns } from "../../api/queries";
import type { WorkflowRun } from "../../api/types";
import { Icons } from "../../ui/Icon";
import { EmptyState } from "../../ui/EmptyState";

// ---- helpers ----------------------------------------------------------------

type StepStatus = "done" | "running" | "failed" | "pending";

function stepStatusFor(i: number, run: WorkflowRun): StepStatus {
  if (i < run.cursor) return "done";
  if (i === run.cursor) {
    if (run.status === "failed") return "failed";
    if (run.status === "completed") return "done";
    return "running";
  }
  return "pending";
}

const STATUS_COLOR: Record<StepStatus, string> = {
  done: "var(--success, #22c55e)",
  running: "var(--accent, #6366f1)",
  failed: "var(--danger, #ef4444)",
  pending: "var(--surface-3, #94a3b8)",
};

function fmt(ts: string | null) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

// ---- sub-components ---------------------------------------------------------

interface StepItemProps {
  index: number;
  containerId: string | undefined;
  status: StepStatus;
  currentTaskId: string | null;
  isError: boolean;
}

function StepItem({ index, containerId, status, currentTaskId, isError }: StepItemProps) {
  const color = STATUS_COLOR[status];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        padding: "12px 14px",
        borderRadius: 10,
        border: `1px solid ${isError ? "var(--danger, #ef4444)" : "var(--surface-3)"}`,
        background: isError ? "rgba(239,68,68,.05)" : "var(--surface-1)",
      }}
    >
      {/* Circle / badge */}
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: color,
          color: "#fff",
          display: "grid",
          placeItems: "center",
          flexShrink: 0,
          fontSize: 12,
          fontWeight: 700,
        }}
      >
        {status === "done" ? <Icons.Check w={12} /> : index + 1}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>Step {index + 1}</span>
          {containerId && (
            <span className="tag" style={{ fontSize: 10.5 }}>{containerId}</span>
          )}
          {/* Status label — lowercase so only one leaf node matches /running/i */}
          <span
            style={{
              marginLeft: "auto",
              fontSize: 11.5,
              fontWeight: 600,
              color,
              textTransform: "capitalize",
            }}
          >
            {status}
          </span>
        </div>

        {/* Task link for the current active step */}
        {status === "running" && currentTaskId && containerId && (
          <div style={{ marginTop: 4 }}>
            <Link
              to={`/containers/${containerId}/tasks/${currentTaskId}`}
              style={{ fontSize: 12, color: "var(--accent, #6366f1)" }}
            >
              View task {currentTaskId}
            </Link>
          </div>
        )}
        {status === "running" && currentTaskId && !containerId && (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--muted)" }}>
            Task: {currentTaskId}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- main page --------------------------------------------------------------

export default function WorkflowRunDetail() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  const { data: workflow } = useWorkflow(id ?? "");
  const { data: runsData } = useWorkflowRuns(id ?? "");

  const runs = runsData?.runs ?? [];
  const run = runs.find((r) => r.id === runId) ?? runs[0];
  const steps = workflow?.steps ?? [];

  if (!run) {
    return (
      <div className="page">
        <div className="page-title">
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {workflow?.name ?? "Workflow"} — Runs
          </div>
        </div>
        <EmptyState
          icon="Checklist"
          title="No runs yet"
          description="Trigger this workflow to see per-step status here."
        />
      </div>
    );
  }

  const stepCount = run.step_count;

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title">
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
          {workflow?.name ?? "Workflow"} — Run
        </div>
        {/* Single subtitle line: "Step 2 of 2" only — status shown inside the stepper */}
        <div style={{ marginTop: 4, fontSize: 13, color: "var(--muted)" }}>
          Step {run.cursor + 1} of {stepCount}
        </div>
        {run.error_message && (
          <div
            className="note"
            style={{ marginTop: 8, color: "var(--danger, #ef4444)", fontSize: 12.5 }}
          >
            {run.error_message}
          </div>
        )}
      </div>

      {/* Vertical stepper */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {Array.from({ length: stepCount }, (_, i) => {
          const step = steps[i];
          const status = stepStatusFor(i, run);
          const isError = run.status === "failed" && run.error_step === i;
          return (
            <StepItem
              key={i}
              index={i}
              containerId={step?.container_id}
              status={status}
              currentTaskId={i === run.cursor ? run.current_task_id : null}
              isError={isError}
            />
          );
        })}
      </div>

      {/* Prior runs (all except the latest) */}
      {runs.length > 1 && (
        <div style={{ marginTop: 24 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.05em",
              marginBottom: 8,
              color: "var(--muted)",
              textTransform: "uppercase",
            }}
          >
            Prior runs
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              border: "1px solid var(--surface-3)",
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            {runs.slice(1).map((r) => (
              <div
                key={r.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 14px",
                  fontSize: 13,
                  borderBottom: "1px solid var(--surface-3)",
                }}
              >
                <span
                  style={{
                    fontWeight: 600,
                    textTransform: "capitalize",
                    color:
                      r.status === "failed"
                        ? "var(--danger, #ef4444)"
                        : r.status === "completed"
                          ? "var(--success, #22c55e)"
                          : "var(--accent, #6366f1)",
                  }}
                >
                  {r.status}
                </span>
                <span style={{ color: "var(--muted)", fontSize: 12 }}>
                  {fmt(r.started_at)}
                </span>
                {r.ended_at && (
                  <span style={{ color: "var(--muted)", fontSize: 12 }}>
                    → {fmt(r.ended_at)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
