import { useParams, useNavigate } from "react-router-dom";
import { useScheduledTask } from "../api/queries";
import { scheduleSummary } from "../lib/scheduleSummary";
import { Button } from "../ui/Button";
import { Icons } from "../ui/Icon";
import type { ScheduleTarget } from "../api/types";

function TargetDetail({ target }: { target: ScheduleTarget }) {
  if (target.kind === "workflow") {
    return (
      <>
        <dt style={{ color: "var(--muted)" }}>Target</dt>
        <dd style={{ margin: 0 }}>Workflow</dd>
        <dt style={{ color: "var(--muted)" }}>Workflow ID</dt>
        <dd style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: 12.5 }}>{target.workflow_id}</dd>
      </>
    );
  }
  return (
    <>
      <dt style={{ color: "var(--muted)" }}>Target</dt>
      <dd style={{ margin: 0 }}>Prompt</dd>
      <dt style={{ color: "var(--muted)" }}>Prompt ID</dt>
      <dd style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: 12.5 }}>{target.prompt_id}</dd>
      <dt style={{ color: "var(--muted)" }}>Container ID</dt>
      <dd style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: 12.5 }}>{target.container_id}</dd>
      {Object.keys(target.variables).length > 0 && (
        <>
          <dt style={{ color: "var(--muted)" }}>Variables</dt>
          <dd style={{ margin: 0 }}>
            {Object.entries(target.variables).map(([k, v]) => (
              <div key={k} style={{ fontSize: 12.5 }}>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--p-700)" }}>{`{{${k}}}`}</span>
                {" = "}
                <span>{v || <em style={{ color: "var(--muted)" }}>empty</em>}</span>
              </div>
            ))}
          </dd>
        </>
      )}
    </>
  );
}

export default function ScheduledTaskDetail() {
  const { sid } = useParams<{ sid: string }>();
  const navigate = useNavigate();
  const q = useScheduledTask(sid!);

  if (q.isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;
  if (q.isError) return <div className="p-8 text-sm text-muted">Couldn't load this scheduled run.</div>;
  const s = q.data;
  if (!s) return <div className="p-8 text-sm text-muted">Not found.</div>;

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
              <Icons.Clock w={20} /> {s.name}
            </h1>
            <span className={`pill ${s.enabled ? "pill-running" : "pill-dormant"}`}>
              <span className="dot" /> {s.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={() => navigate(`/schedules/${sid}/edit`)}>
            Edit
          </Button>
        </div>
      </div>

      <div className="card" style={{ maxWidth: 760 }}>
        <dl style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "10px 0", fontSize: 13.5, margin: 0 }}>
          <TargetDetail target={s.target} />
          <dt style={{ color: "var(--muted)" }}>Schedule</dt>
          <dd style={{ margin: 0 }}>{scheduleSummary(s.schedule, s.timezone, s.next_run_at)}</dd>
          <dt style={{ color: "var(--muted)" }}>Next run</dt>
          <dd style={{ margin: 0 }}>{s.enabled && s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</dd>
          <dt style={{ color: "var(--muted)" }}>Last run</dt>
          <dd style={{ margin: 0 }}>{s.last_run_at ? new Date(s.last_run_at).toLocaleString() : "—"}</dd>
          <dt style={{ color: "var(--muted)" }}>Last status</dt>
          <dd style={{ margin: 0 }}>{s.last_status ?? "—"}</dd>
        </dl>
      </div>
    </div>
  );
}
