import { Link } from "react-router-dom";
import type { TenantTaskSummary } from "../api/types";
import { TaskBadge } from "./StatusBadge";
import { formatCompact } from "../lib/format";
import { EmptyState } from "../ui/EmptyState";

export function ActivityFeed({ tasks }: { tasks: TenantTaskSummary[] }) {
  if (tasks.length === 0) {
    return (
      <EmptyState
        size="sm"
        icon="History"
        title="No recent tasks"
        description="Tasks run across your containers show up here."
      />
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {tasks.map((t) => (
        <Link key={t.task_id} to={`/containers/${t.container_id}/tasks/${t.task_id}`}
          style={{ display: "grid", gridTemplateColumns: "1fr 96px 52px", gap: 10,
            alignItems: "center", padding: "9px 0", borderBottom: "1px solid var(--surface-3)",
            textDecoration: "none", color: "inherit" }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>
            {t.container_name ?? t.container_id}
          </span>
          <span style={{ justifySelf: "center" }}>
            <TaskBadge status={t.status} />
          </span>
          <span className="num" style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--muted)", textAlign: "right" }}>
            {formatCompact(t.tokens_in + t.tokens_out)}
          </span>
        </Link>
      ))}
    </div>
  );
}
