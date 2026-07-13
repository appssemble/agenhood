import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTasks, useContainer } from "../api/queries";
import { TaskBadge } from "../components/StatusBadge";
import { ConfigDiff } from "../components/ConfigDiff";
import { EventFeed } from "../components/EventFeed";
import { SegControl } from "../ui/SegControl";
import { Icons } from "../ui/Icon";
import type { Event, TaskStatus, TaskSummary } from "../api/types";

type Filter = "all" | "completed" | "failed" | "cancelled";

const FILTER_OPTIONS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function matchesFilter(status: TaskStatus, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "cancelled") return status === "cancelled" || status === "timed_out";
  return status === filter;
}

function Replay({ cid, tid }: { cid: string; tid: string }) {
  const { data } = useQuery({
    queryKey: ["containers", cid, "tasks", tid, "replay"],
    queryFn: () => api.get<{ events: Event[] }>(`/v1/containers/${cid}/tasks/${tid}/events`),
  });
  const events = data?.events ?? [];
  return (
    <div style={{ marginTop: 20, paddingTop: 20, borderTop: "1px dashed var(--border)" }}>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--muted)",
          textTransform: "uppercase",
          letterSpacing: ".08em",
          fontWeight: 700,
          marginBottom: 12,
        }}
      >
        Event replay
      </div>
      <EventFeed events={events} cid={cid} />
    </div>
  );
}

function HistRow({
  t,
  selected,
  onSelect,
}: {
  t: TaskSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
      style={{
        padding: "12px 18px",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 8,
        background: selected ? "var(--p-100)" : "transparent",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div className="clamp-2" style={{ fontWeight: 600, fontSize: 13 }} title={t.prompt}>{t.prompt}</div>
        <div className="id" style={{ marginTop: 2 }}>
          {t.task_id}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
        <TaskBadge status={t.status} />
        <span className="id">{(t.tokens_in + t.tokens_out).toLocaleString()} tk</span>
      </div>
    </div>
  );
}

export default function TaskHistory() {
  const { cid } = useParams<{ cid: string }>();
  const { data: tasksData } = useTasks(cid!);
  const { data: container } = useContainer(cid!);
  const tasks = tasksData?.tasks ?? [];
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get("task");
  const setSelected = (id: string) =>
    setSearchParams(
      (prev) => {
        prev.set("task", id);
        return prev;
      },
      { replace: true },
    );
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = tasks.filter((t) => matchesFilter(t.status, filter));
  const sel = tasks.find((t) => t.task_id === selected);

  return (
    <div
      className="responsive-split"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 0,
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-3)",
      }}
    >
      {/* Left pane — task list */}
      <div
        style={{
          overflow: "auto",
          borderRight: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "12px 18px",
            display: "flex",
            alignItems: "center",
            gap: 10,
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span style={{ fontWeight: 700, fontSize: 13.5 }}>Tasks</span>
          <span className="id">{tasks.length} total</span>
          <div style={{ marginLeft: "auto" }}>
            <SegControl options={FILTER_OPTIONS} value={filter} onChange={setFilter} />
          </div>
        </div>

        {/* Task list */}
        {filtered.map((t) => (
          <HistRow
            key={t.task_id}
            t={t}
            selected={selected === t.task_id}
            onSelect={() => setSelected(t.task_id)}
          />
        ))}
        {filtered.length === 0 && (
          <p style={{ padding: "24px 18px", fontSize: 13, color: "var(--muted)" }}>
            No tasks match this filter.
          </p>
        )}
      </div>

      {/* Right pane — task detail */}
      <div style={{ overflow: "auto", background: "var(--surface-2)" }}>
        {sel ? (
          <>
            {/* Task header */}
            <div
              style={{
                padding: "22px 24px",
                background: "var(--surface)",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              <div>
                <div className="id">{sel.task_id}</div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 500,
                    lineHeight: 1.55,
                    color: "var(--ink-2)",
                    marginTop: 6,
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                  }}
                >
                  {sel.prompt}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <TaskBadge status={sel.status} />
                <span className="chip">
                  {(sel.tokens_in + sel.tokens_out).toLocaleString()} tokens
                </span>
                {sel.config_snapshot && (
                  <span className="chip">
                    {sel.config_snapshot.driver} · {sel.config_snapshot.model}
                    {sel.config_snapshot.effort ? ` · ${sel.config_snapshot.effort}` : ""}
                  </span>
                )}
              </div>
              <div>
                <button className="btn btn-primary">
                  <Icons.Refresh w={14} /> Re-submit (current config)
                </button>
              </div>
            </div>

            {/* Config snapshot section */}
            <div style={{ padding: "22px 24px" }}>
              {sel.config_snapshot ? (
                <>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      marginBottom: 14,
                    }}
                  >
                    <h3
                      style={{ margin: 0, fontSize: 14.5, fontWeight: 700 }}
                    >
                      Config snapshot · diff against current
                    </h3>
                  </div>
                  <div className="note amber" style={{ marginBottom: 14 }}>
                    <b>Why did this task behave differently?</b> Below is the exact config this
                    task ran with, compared to the container's current config. Differences are
                    highlighted.
                  </div>
                  {container ? (
                    <ConfigDiff snapshot={sel.config_snapshot} current={container.config} />
                  ) : (
                    <dl className="mt-3" style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "4px 0", fontSize: 13 }}>
                      <dt style={{ color: "var(--muted)" }}>Driver</dt>
                      <dd className="mono">{sel.config_snapshot.driver}</dd>
                      <dt style={{ color: "var(--muted)" }}>Model</dt>
                      <dd className="mono">{sel.config_snapshot.model}</dd>
                      <dt style={{ color: "var(--muted)" }}>Prompt mode</dt>
                      <dd>{sel.config_snapshot.system_prompt_mode}</dd>
                      <dt style={{ color: "var(--muted)" }}>Tools</dt>
                      <dd>{sel.config_snapshot.tools.join(", ") || "—"}</dd>
                    </dl>
                  )}
                  <div className="note" style={{ marginTop: 14 }}>
                    <b>Hypothesis:</b> review the diff above to understand how configuration
                    changes may have affected this task's behaviour.
                  </div>
                </>
              ) : (
                <p style={{ fontSize: 13, color: "var(--muted)" }}>
                  No config snapshot recorded for this task.
                </p>
              )}

              <Replay cid={cid!} tid={sel.task_id} />
            </div>
          </>
        ) : (
          <p
            style={{
              padding: "24px 18px",
              fontSize: 13,
              color: "var(--muted)",
            }}
          >
            Select a task to see its config snapshot and replay its events.
          </p>
        )}
      </div>
    </div>
  );
}
