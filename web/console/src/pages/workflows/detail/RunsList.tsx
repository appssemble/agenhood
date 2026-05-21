import { Button } from "../../../ui/Button";
import { Icons } from "../../../ui/Icon";
import { EmptyState } from "../../../ui/EmptyState";
import type { WorkflowRun } from "../../../api/types";
import { formatDuration, STEP_BADGE_COLOR, stepStatusFromRun, timeAgo } from "./derive";
import { shortId } from "../../../lib/format";

type Status = WorkflowRun["status"];

const STATUS_META: Record<Status, { bg: string; fg: string; word: string }> = {
  completed: { bg: "var(--success-100)", fg: "var(--success-700)", word: "Completed" },
  running: { bg: "var(--info-100)", fg: "var(--info-700)", word: "Running" },
  failed: { bg: "var(--err-100)", fg: "var(--err-700)", word: "Failed" },
};

function StatusIcon({ status }: { status: Status }) {
  const m = STATUS_META[status];
  return (
    <span
      aria-hidden
      style={{
        width: 30, height: 30, borderRadius: 9, background: m.bg, color: m.fg,
        display: "grid", placeItems: "center", flexShrink: 0,
      }}
    >
      {status === "completed" ? <Icons.Check w={14} />
        : status === "failed" ? <Icons.Close w={13} />
        : <span className="spinner" />}
    </span>
  );
}

function triggerMeta(src: string): { icon: React.ReactNode; label: string } {
  switch (src) {
    case "schedule": return { icon: <Icons.Clock w={11} />, label: "Scheduled" };
    case "manual": return { icon: <Icons.Play w={11} />, label: "Manual" };
    case "api": return { icon: <Icons.Bolt w={11} />, label: "API" };
    default: return { icon: <Icons.Bolt w={11} />, label: src };
  }
}

/** Mini per-step progress, coloured with the same scale as the pipeline. Segments
 *  for small workflows; a proportional bar once there are too many to read. */
function StepProgress({ run }: { run: WorkflowRun }) {
  const n = Math.max(run.step_count, 1);
  const reached = run.status === "completed" ? n : Math.min(run.cursor + 1, n);
  const label = run.status === "completed" ? `${n}/${n} steps` : `step ${reached}/${n}`;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, width: 120 }}>
      {n <= 14 ? (
        <div style={{ display: "flex", gap: 3 }}>
          {Array.from({ length: n }, (_, i) => {
            const st = stepStatusFromRun(run, i);
            return (
              <span key={i} style={{
                flex: 1, height: 5, borderRadius: 999,
                background: st === "pending" ? "var(--surface-3)" : STEP_BADGE_COLOR[st],
              }} />
            );
          })}
        </div>
      ) : (
        <div style={{ height: 5, borderRadius: 999, background: "var(--surface-3)", overflow: "hidden" }}>
          <span style={{
            display: "block", height: "100%", width: `${(reached / n) * 100}%`,
            background: run.status === "failed" ? "var(--err-500)" : "var(--success-500)",
          }} />
        </div>
      )}
      <span className="mono" style={{ fontSize: 10.5, color: "var(--muted-2)" }}>{label}</span>
    </div>
  );
}

function durationLabel(r: WorkflowRun, nowMs: number): string {
  if (r.status === "running" && r.started_at) return formatDuration(nowMs - Date.parse(r.started_at));
  if (r.started_at && r.ended_at) return formatDuration(Date.parse(r.ended_at) - Date.parse(r.started_at));
  return "—";
}

export function RunsList({
  runs, selectedRunId, onSelect, nowMs, onRunNow, running,
}: {
  runs: WorkflowRun[];
  selectedRunId: string | null;
  onSelect: (id: string) => void;
  nowMs: number;
  onRunNow: () => void;
  running: boolean;
}) {
  return (
    <div className="card flush">
      <div className="card-head">
        <h3>Runs</h3>
        <span className="spacer" />
        {runs.length > 0 && <span style={{ fontSize: 11.5, color: "var(--muted)" }}>Last {runs.length}</span>}
      </div>
      {runs.length === 0 ? (
        <div style={{ padding: 24 }}>
          <EmptyState
            icon="History"
            title="No runs yet"
            description="Trigger this workflow to see its pipeline come to life."
            actions={
              <Button variant="primary" size="sm" disabled={running} onClick={onRunNow}>
                <Icons.Play w={14} /> Run now
              </Button>
            }
          />
        </div>
      ) : (
        <div>
          {runs.map((r) => {
            const sel = selectedRunId === r.id;
            const tg = triggerMeta(r.trigger_source);
            const sm = STATUS_META[r.status];
            return (
              <button
                key={r.id}
                type="button"
                aria-current={sel ? "true" : undefined}
                onClick={() => onSelect(r.id)}
                style={{
                  width: "100%", display: "grid",
                  gridTemplateColumns: "auto minmax(0, 1fr) auto auto",
                  alignItems: "center", gap: 16, padding: "12px 16px",
                  borderTop: "1px solid var(--surface-3)", textAlign: "left", cursor: "pointer",
                  background: sel ? "var(--p-50)" : "transparent",
                }}
              >
                <StatusIcon status={r.status} />

                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                    {timeAgo(r.started_at, nowMs)}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600, color: "var(--muted)" }}>
                      {tg.icon} {tg.label}
                    </span>
                    <span className="mono" title={r.id} style={{ fontSize: 10.5, color: "var(--muted-2)" }}>
                      {shortId(r.id)}
                    </span>
                  </div>
                </div>

                <StepProgress run={r} />

                <div style={{ textAlign: "right", minWidth: 64 }}>
                  <div className="mono num" style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                    {durationLabel(r, nowMs)}
                  </div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: sm.fg, marginTop: 2 }}>
                    {r.status === "failed" && r.error_step != null ? `at step ${r.error_step + 1}` : sm.word}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
