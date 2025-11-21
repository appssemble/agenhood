// web/console/src/pages/Tasks.tsx
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTenantTasks } from "../api/queries";
import { TaskBadge } from "../components/StatusBadge";
import { SegControl } from "../ui";
import { EmptyRow } from "../ui/EmptyState";

type Filter = "all" | "running" | "completed" | "failed";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

export default function Tasks() {
  const navigate = useNavigate();
  const { data, isLoading } = useTenantTasks(50);
  const [filter, setFilter] = useState<Filter>("all");
  const tasks = data?.tasks ?? [];
  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;

  return (
    <div className="page">
      <div className="page-title" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>Tasks</h1>
        <span className="pill pill-dormant" style={{ fontWeight: 500 }}>{tasks.length} across the fleet</span>
        <div style={{ marginLeft: "auto" }}>
          <SegControl options={FILTERS} value={filter} onChange={setFilter} />
        </div>
      </div>

      <div className="card flush">
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Task</th>
              <th>Container</th>
              <th style={{ textAlign: "center" }}>Status</th>
              <th>Tokens</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr
                key={t.task_id}
                onClick={(e) => {
                  // Row opens the container history with this task selected,
                  // except clicks on inline controls (e.g. the container link).
                  if ((e.target as HTMLElement).closest("button, a")) return;
                  navigate(`/containers/${t.container_id}/history?task=${t.task_id}`);
                }}
                style={{ cursor: "pointer" }}
              >
                <td><div className="clamp-2" style={{ fontWeight: 600 }} title={t.prompt}>{t.prompt}</div><div className="id">{t.task_id}</div></td>
                <td>
                  <Link to={`/containers/${t.container_id}/tasks/${t.task_id}`} style={{ color: "inherit", textDecoration: "none", fontWeight: 600 }}>
                    {t.container_name ?? t.container_id}
                  </Link>
                </td>
                <td style={{ textAlign: "center" }}><TaskBadge status={t.status} /></td>
                <td className="num">{(t.tokens_in + t.tokens_out).toLocaleString()}</td>
                <td><span className="id">{t.created_at}</span></td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <EmptyRow
                colSpan={5}
                icon="Tasks"
                title={tasks.length === 0 ? "No tasks yet" : "No matching tasks"}
                description={
                  tasks.length === 0
                    ? "Submit a task to a container and it will show up here across the fleet."
                    : "No tasks match the selected status filter. Try “All”."
                }
              />
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
