import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTask, useCancelTask } from "../api/queries";
import { api } from "../api/client";
import { subscribeEvents } from "../api/events";
import { TaskBadge } from "../components/StatusBadge";
import { ConfirmBar } from "../components/ConfirmBar";
import { TokenMeter } from "../components/TokenMeter";
import { EventFeed } from "../components/EventFeed";
import { TaskBrief } from "../components/TaskBrief";
import { ResultPanel } from "../components/ResultPanel";
import { FilesPanel } from "../components/FilesPanel";
import { TaskRail } from "../components/TaskRail";
import { useToast } from "../components/Toast";
import { useAuth } from "../auth/useAuth";
import { ApiError } from "../api/client";
import type { AgentConfig, Event } from "../api/types";
import { containerFileRawUrl } from "../api/fileUrls";

type Conn = "connecting" | "live" | "reconnecting";
type Tab = "activity" | "result" | "files" | "config";

function downloadHref(cid: string, path: string) {
  return containerFileRawUrl(cid, path);
}

/** Selected fields of the config snapshot, in a compact key/value grid. */
function ConfigSnapshot({ config }: { config: AgentConfig }) {
  const rows: [string, string][] = [
    ["Driver", config.driver],
    ["Model", config.model],
    ["Tools", config.tools.length ? config.tools.join(", ") : "—"],
    ["Skills", config.skills?.length ? config.skills.join(", ") : "—"],
    ["Max iterations", config.max_iterations != null ? String(config.max_iterations) : "default"],
    ["Max tokens", config.max_tokens != null ? config.max_tokens.toLocaleString() : "default"],
    ["Timeout", config.timeout_seconds != null ? `${config.timeout_seconds}s` : "default"],
  ];
  return (
    <div style={{ padding: 20 }}>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd className={k === "Tools" || k === "Model" || k === "Driver" ? "mono" : undefined}>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function TaskViewer() {
  const { cid, tid } = useParams<{ cid: string; tid: string }>();
  const taskQ = useTask(cid!, tid!);
  const cancel = useCancelTask(cid!, tid!);
  const toast = useToast();
  const { user } = useAuth();

  const [events, setEvents] = useState<Event[]>([]);
  const [conn, setConn] = useState<Conn>("connecting");
  const [tokens, setTokens] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [tab, setTab] = useState<Tab>("activity");
  const lastSeq = useRef(0);
  const tabInit = useRef(false);

  const status = taskQ.data?.status;
  const terminal = !!status && status !== "running" && status !== "pending";

  // live elapsed counter while running
  useEffect(() => {
    if (terminal || !taskQ.data?.started_at) return;
    const start = new Date(taskQ.data.started_at).getTime();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [terminal, taskQ.data?.started_at]);

  // SSE subscription; resumes with after_seq on reconnect
  useEffect(() => {
    if (!cid || !tid || terminal) return;
    setConn("connecting");
    const stop = subscribeEvents(cid, tid, {
      afterSeq: lastSeq.current || undefined,
      onOpen: () => setConn("live"),
      onEvent: (e) => {
        setConn("live");
        lastSeq.current = e.seq;
        setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e]));
        if (e.type === "token_update") setTokens((e.payload.tokens_in as number) + (e.payload.tokens_out as number));
        if (e.type === "status_change") taskQ.refetch();
      },
      onError: () => setConn("reconnecting"),
    });
    return stop;
  }, [cid, tid, terminal]);

  // Finished tasks have no live stream — replay the recorded events instead.
  const replayQ = useQuery({
    queryKey: ["containers", cid, "tasks", tid, "replay"],
    queryFn: () => api.get<{ events: Event[] }>(`/v1/containers/${cid}/tasks/${tid}/events`),
    enabled: !!cid && !!tid && terminal,
  });

  // Live SSE while running; recorded replay once terminal.
  const feedEvents = terminal ? replayQ.data?.events ?? [] : events;

  const result = taskQ.data?.result as { success?: boolean; output?: unknown; files?: string[]; reason?: string | null } | null | undefined;
  const error = taskQ.data?.error ?? null;
  const tokenCap = user?.tenant?.limits?.default_max_tokens ?? null;

  // On first load, land a finished task with output on the Result tab.
  useEffect(() => {
    if (tabInit.current || !taskQ.data) return;
    tabInit.current = true;
    if (terminal && result?.output != null) setTab("result");
  }, [taskQ.data, terminal, result?.output]);

  // Steps (iterations) from events
  const steps = feedEvents.filter((e) => e.type === "iteration_started").map((e) => (e.payload as Record<string, any>).iteration as number);
  const lastIteration = steps.length;

  const elapsedMins = Math.floor(elapsed / 60);
  const elapsedSecs = String(elapsed % 60).padStart(2, "0");

  // Files changed from events (dedupe by path, keep last op)
  const filesChanged = (() => {
    const map = new Map<string, string>();
    for (const ev of feedEvents) {
      if (ev.type === "file_changed") {
        const p = ev.payload as Record<string, any>;
        map.set(p.path as string, p.operation as string);
      }
    }
    return [...map.entries()].map(([path, op]) => ({ path, op }));
  })();

  // Tools used from events
  const toolsUsed = (() => {
    const counts = new Map<string, number>();
    for (const ev of feedEvents) {
      if (ev.type === "tool_call") {
        const p = ev.payload as Record<string, any>;
        counts.set(p.name as string, (counts.get(p.name as string) ?? 0) + 1);
      }
    }
    return [...counts.entries()].map(([name, n]) => ({ name, n }));
  })();

  const title = (taskQ.data?.prompt ?? "Loading…").split("\n")[0];
  const showRail = tab === "activity";
  const config = taskQ.data?.config_snapshot;

  return (
    <div className="task-screen">
      {/* Identity strip — fixed height, length-proof */}
      <header className="task-strip">
        <div className="title-stack">
          <span className="name">{title}</span>
          <span className="id">{tid} · {cid}</span>
        </div>
        <div className="meta">
          {status && <TaskBadge status={status} />}
          {!terminal && (
            <span className={`conn${conn === "reconnecting" ? " reconnect" : ""}`}>
              <span className="pulse" style={{ background: conn === "reconnecting" ? "var(--warn-500)" : "var(--p-300)" }} />
              {conn === "live" ? "live" : conn === "reconnecting" ? "reconnecting…" : "connecting…"}
            </span>
          )}
          {lastIteration > 0 && <span className="chip">step <b>{lastIteration}</b></span>}
          {!terminal && <span className="chip">elapsed <b>{elapsedMins}:{elapsedSecs}</b></span>}
        </div>
        <div className="actions">
          <TokenMeter used={tokens} cap={tokenCap} />
          {!terminal && (
            <button className="btn btn-danger btn-sm" onClick={() => setConfirmCancel(true)}>
              Cancel
            </button>
          )}
        </div>
      </header>

      {/* Inline cancel confirm */}
      {confirmCancel && (
        <div style={{ padding: "8px 16px", flexShrink: 0 }}>
          <ConfirmBar
            message="Cancel this task? Tokens consumed so far will still be billed."
            confirmLabel="Yes, cancel task"
            cancelLabel="Keep running"
            onConfirm={async () => {
              try { await cancel.mutateAsync(); setConfirmCancel(false); }
              catch (err) { toast.error("Couldn't cancel task", err instanceof ApiError ? err.message : undefined); }
            }}
            onCancel={() => setConfirmCancel(false)}
          />
        </div>
      )}

      {/* Task brief — dedicated scrollable section for long prompts */}
      <TaskBrief prompt={taskQ.data?.prompt ?? ""} />

      {/* Error banner */}
      {error && (
        <div className="task-error" role="alert">
          <span className="code">{error.code}</span>
          <span>{error.message}</span>
        </div>
      )}

      {/* Work area: tabs + body + contextual rail */}
      <div className={`task-body${showRail ? "" : " no-rail"}`}>
        <div className="tabs">
          <button className={`tab${tab === "activity" ? " active" : ""}`} onClick={() => setTab("activity")}>
            Activity
          </button>
          <button className={`tab${tab === "result" ? " active" : ""}`} onClick={() => setTab("result")}>
            Result
          </button>
          <button className={`tab${tab === "files" ? " active" : ""}`} onClick={() => setTab("files")}>
            Files {filesChanged.length > 0 && <span className="count">{filesChanged.length}</span>}
          </button>
          {config && (
            <button className={`tab${tab === "config" ? " active" : ""}`} onClick={() => setTab("config")}>
              Config
            </button>
          )}
        </div>

        <div className="task-pane">
          {tab === "activity" && (
            <>
              <EventFeed events={feedEvents} cid={cid!} />
              {feedEvents.length === 0 && (
                <div style={{ padding: 16, fontSize: 13, color: "var(--muted)" }}>
                  {!terminal
                    ? "Waiting for events…"
                    : replayQ.isLoading
                      ? "Loading event replay…"
                      : "No events were recorded for this task."}
                </div>
              )}
            </>
          )}
          {tab === "result" && (
            <ResultPanel result={result} terminal={terminal} downloadHref={(p) => downloadHref(cid!, p)} />
          )}
          {tab === "files" && (
            <FilesPanel files={filesChanged} downloadHref={(p) => downloadHref(cid!, p)} />
          )}
          {tab === "config" && config && <ConfigSnapshot config={config} />}
        </div>

        {showRail && <TaskRail steps={steps} tools={toolsUsed} />}
      </div>
    </div>
  );
}
