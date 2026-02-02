import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useScheduledTasks,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePrompts,
  useWorkflows,
} from "../api/queries";
import { scheduleParts } from "../lib/scheduleSummary";
import { relativeFromNow, formatDateTime } from "../lib/format";
import { ApiError } from "../api/client";
import { useToast } from "../components/Toast";
import { Button } from "../ui/Button";
import { Icons } from "../ui/Icon";
import { SegControl } from "../ui/SegControl";
import { EmptyState } from "../ui/EmptyState";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ScheduledCalendar } from "./ScheduledCalendar";
import type { ScheduledTask, Prompt, Workflow } from "../api/types";

/** Labeled enable/disable control: a switch + an "Active"/"Paused" state word, so
 *  it's obvious what it toggles and what the current state is. */
function EnableToggle({ sid, enabled }: { sid: string; enabled: boolean }) {
  const update = useUpdateScheduledTask(sid);
  const toast = useToast();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={enabled ? "Active — click to pause this scheduled run" : "Paused — click to activate this scheduled run"}
      className={`sched-toggle ${enabled ? "on" : ""}`.trim()}
      disabled={update.isPending}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await update.mutateAsync({ enabled: !enabled });
        } catch (err) {
          toast.error("Couldn't update scheduled run", err instanceof ApiError ? err.message : undefined);
        }
      }}
    >
      <span className="sched-toggle-sw" aria-hidden />
      <span className="sched-toggle-lab">{enabled ? "Active" : "Paused"}</span>
    </button>
  );
}

/** Resolve a schedule's target into an icon + human name (falls back to the id). */
function targetInfo(s: ScheduledTask, prompts: Prompt[], workflows: Workflow[]): { icon: React.ReactNode; name: string } {
  if (s.target.kind === "workflow") {
    const wid = s.target.workflow_id; // hoist the narrowed id out of the closure below
    return { icon: <Icons.Workflow w={11} />, name: workflows.find((w) => w.id === wid)?.name ?? wid };
  }
  const pid = s.target.prompt_id;
  return { icon: <Icons.Prompt w={11} />, name: prompts.find((p) => p.id === pid)?.name ?? pid };
}

function dot(bg: string): React.CSSProperties {
  return { width: 7, height: 7, borderRadius: 999, background: bg, display: "inline-block", flex: "0 0 auto" };
}

/** The last run's outcome as a clear icon + plain-English label (not a pill). */
function Outcome({ status }: { status: string | null }) {
  let icon: React.ReactNode;
  let label: string;
  let color: string;
  let hint: string | undefined;
  switch (status) {
    // The scheduler records whether the last firing dispatched a run, not the
    // run's own completion — "submitted" is the normal healthy outcome.
    case "submitted":
      icon = <Icons.Send w={11} />; label = "Dispatched"; color = "var(--info-700)";
      hint = "The scheduled run was dispatched successfully"; break;
    case "completed": icon = <Icons.Check w={12} />; label = "Succeeded"; color = "var(--success-700)"; break;
    case "failed": icon = <Icons.Close w={12} />; label = "Failed"; color = "var(--err-700)"; break;
    case "running": icon = <span className="spinner" style={{ width: 10, height: 10 }} />; label = "Running"; color = "var(--info-700)"; break;
    case "skipped_overlap":
      icon = <span style={dot("var(--warn-500)")} />; label = "Skipped"; color = "var(--warn-700)";
      hint = "Skipped — the previous run was still in progress"; break;
    default: icon = <span style={dot("var(--muted-2)")} />; label = status ?? "—"; color = "var(--muted)";
  }
  // Inline (not flex) so the LABEL TEXT drives the baseline; only the icon is
  // vertically centred against the text.
  return (
    <span style={{ color, fontWeight: 600, whiteSpace: "nowrap" }} title={hint}>
      <span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: 4 }}>{icon}</span>
      {label}
    </span>
  );
}

export default function ScheduledTasks() {
  const navigate = useNavigate();
  const toast = useToast();
  const q = useScheduledTasks();
  const del = useDeleteScheduledTask();
  const prompts = usePrompts().data?.prompts ?? [];
  const workflows = useWorkflows().data?.workflows ?? [];
  const [deleting, setDeleting] = useState<ScheduledTask | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [view, setView] = useState<"table" | "calendar">(() => {
    try { return localStorage.getItem("schedules.view") === "calendar" ? "calendar" : "table"; } catch { return "table"; }
  });
  function changeView(v: "table" | "calendar") {
    setView(v);
    try { localStorage.setItem("schedules.view", v); } catch { /* ignore */ }
  }

  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  async function confirmDelete() {
    const id = deleting?.id;
    setDeleting(null);
    if (!id) return;
    try {
      await del.mutateAsync(id);
    } catch (err) {
      toast.error("Couldn't delete scheduled run", err instanceof ApiError ? err.message : undefined);
    }
  }

  if (q.isLoading) return <div className="page"><div className="note">Loading…</div></div>;
  if (q.isError) return <div className="page"><div className="note">Couldn't load scheduled runs.</div></div>;
  const items = q.data?.scheduled_tasks ?? [];

  const newButton = (
    <Button variant="primary" style={{ gap: 6 }} onClick={() => navigate("/schedules/new")}>
      <Icons.Plus w={14} /> New scheduled run
    </Button>
  );

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Scheduled runs</div>
              {items.length > 0 && (
                <span className="pill pill-dormant" style={{ fontWeight: 600 }}>{items.length}</span>
              )}
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              Run a prompt or workflow automatically — once, or on a recurring cadence.
            </div>
          </div>
          {items.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <SegControl
                value={view}
                onChange={changeView}
                options={[
                  { value: "table", label: <><Icons.Logs w={13} /> Table</> },
                  { value: "calendar", label: <><Icons.Calendar w={13} /> Calendar</> },
                ]}
              />
              {newButton}
            </div>
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <div className="card flush">
          <div style={{ padding: 28 }}>
            <EmptyState
              icon="Clock"
              title="No scheduled runs yet"
              description="Schedule a prompt or workflow to run automatically — once, or on a recurring cadence."
              actions={newButton}
            />
          </div>
        </div>
      ) : view === "calendar" ? (
        <ScheduledCalendar items={items} prompts={prompts} workflows={workflows} />
      ) : (
        <div className="card flush">
          <div>
            {items.map((s) => {
              const t = targetInfo(s, prompts, workflows);
              return (
                <div
                  key={s.id}
                  className="sched-row"
                  onClick={(e) => {
                    if ((e.target as HTMLElement).closest("button, a")) return;
                    navigate(`/schedules/${s.id}`);
                  }}
                >
                  {/* name + target */}
                  <div style={{ minWidth: 0 }}>
                    <Link to={`/schedules/${s.id}`} style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)", textDecoration: "none", display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.name}
                    </Link>
                    <span className="tag" style={{ fontSize: 10.5, marginTop: 4 }}>{t.icon} {t.name}</span>
                  </div>

                  {/* schedule — label + cadence chip on one line, detail beneath */}
                  {(() => {
                    const parts = scheduleParts(s.schedule, s.timezone);
                    return (
                      <div className="sched-col-sched" style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
                          <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted-2)", flexShrink: 0 }}>Cadence</span>
                          <span className={`sched-cadence ${parts.recurring ? "rec" : "once"}`} title="Recurrence">
                            {parts.cadence}
                          </span>
                        </div>
                        {parts.detail && (
                          <span style={{ fontSize: 11.5, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {parts.detail}
                          </span>
                        )}
                      </div>
                    );
                  })()}

                  {/* next / last — identical flex rows so labels + values line up */}
                  <div className="sched-col-runs" style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
                      <span className="sched-meta-lab">Next</span>
                      {!s.enabled ? <span style={{ color: "var(--muted-2)" }}>paused</span>
                        : s.next_run_at ? <span style={{ color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{relativeFromNow(s.next_run_at, nowMs)} · {formatDateTime(s.next_run_at)}</span>
                        : <span style={{ color: "var(--muted-2)" }}>—</span>}
                    </div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
                      <span className="sched-meta-lab">Last</span>
                      {s.last_run_at
                        ? <span style={{ minWidth: 0 }}>
                            <Outcome status={s.last_status} />
                            <span style={{ color: "var(--muted)" }}> · {relativeFromNow(s.last_run_at, nowMs)}</span>
                          </span>
                        : <span style={{ color: "var(--muted-2)" }}>Never run</span>}
                    </div>
                  </div>

                  {/* actions */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <EnableToggle sid={s.id} enabled={s.enabled} />
                    <Link to={`/schedules/${s.id}/edit`} className="btn btn-ghost btn-sm" aria-label={`Edit ${s.name}`}><Icons.Pencil w={14} /> Edit</Link>
                    <Button variant="danger" size="sm" disabled={del.isPending} aria-label={`Delete ${s.name}`}
                      onClick={(e) => { e.stopPropagation(); setDeleting(s); }}>
                      <Icons.Trash w={14} /> Delete
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete scheduled run"
        body={`Delete "${deleting?.name}"? This stops all future runs and cannot be undone.`}
        confirmLabel="Delete scheduled run"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
