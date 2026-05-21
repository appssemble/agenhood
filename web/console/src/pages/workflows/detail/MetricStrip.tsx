import { Pill } from "../../../ui/Pill";
import { Icons } from "../../../ui/Icon";
import type { WorkflowRun } from "../../../api/types";
import { formatDuration, runMetrics, timeAgo } from "./derive";

const RUN_PILL: Record<WorkflowRun["status"], "success" | "running" | "error"> = {
  completed: "success", running: "running", failed: "error",
};

function Stat({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="stack">
      <span className="lab">{k}</span>
      <span className="val num" style={{ display: "flex", alignItems: "center", gap: 6 }}>{children}</span>
    </div>
  );
}

/**
 * The workflow hub's dark top card — shares the `.summary-strip` look with the
 * container detail screen (var(--ink) background, white text, mono labels):
 * title + schedule pill + run metrics + actions in one bar.
 */
export function MetricStrip({
  name, workflowId, scheduled, stepCount, lastRun, metrics, containerCount, nowMs, actions,
}: {
  name: string;
  workflowId: string;
  scheduled: boolean;
  stepCount: number;
  lastRun: WorkflowRun | undefined;
  metrics: ReturnType<typeof runMetrics>;
  containerCount: number;
  nowMs: number;
  actions?: React.ReactNode;
}) {
  return (
    <div className="summary-strip">
      <div className="stack title-stack">
        <h1 className="name" style={{ margin: 0, display: "flex", alignItems: "center", gap: 9 }}>
          <Icons.Workflow w={18} /> {name}
        </h1>
        <span className="id" style={{ fontSize: 11.5 }}>{workflowId}</span>
      </div>

      {scheduled && (<><div className="sep" /><Pill tone="brand">Scheduled</Pill></>)}

      <div className="sep" />
      <Stat k="Steps">{stepCount}</Stat>
      <div className="sep" />
      <Stat k="Last run">
        {lastRun ? (
          <>
            {timeAgo(lastRun.started_at, nowMs)}
            <Pill tone={RUN_PILL[lastRun.status]}>{lastRun.status}</Pill>
          </>
        ) : "—"}
      </Stat>
      <div className="sep" />
      <Stat k="Success rate">
        {metrics.successRate === null ? "—" : `${metrics.completed}/${metrics.completed + metrics.failed}`}
      </Stat>
      <div className="sep" />
      <Stat k="Avg duration">
        {metrics.avgDurationMs === null ? "—" : formatDuration(metrics.avgDurationMs)}
      </Stat>
      <div className="sep" />
      <Stat k="Containers">{containerCount}</Stat>

      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
