import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useTask, useTaskEvents, useCancelTask, keys } from "../api/queries";
import { useTaskStream } from "../api/useTaskStream";
import { TaskBadge } from "./StatusBadge";
import { ChatTimeline } from "./ChatTimeline";
import { useToast } from "./Toast";
import { ApiError } from "../api/client";
import { Icons } from "../ui/Icon";
import type { TaskStatus } from "../api/types";

function isTerminal(s?: TaskStatus) {
  return !!s && s !== "running" && s !== "pending";
}
function isFailed(s: TaskStatus) {
  return s === "failed" || s === "timed_out" || s === "cancelled";
}

// Live turn: subscribes to the task's event stream and renders the transcript as
// it arrives. Used for running and just-submitted tasks.
function ActiveTurnBody({
  cid, taskId, initialStatus, onContentChange,
}: {
  cid: string; taskId: string; initialStatus?: TaskStatus; onContentChange?: () => void;
}) {
  const taskQ = useTask(cid, taskId);
  const qc = useQueryClient();
  const [done, setDone] = useState(false);
  const { events, conn } = useTaskStream(cid, taskId, { enabled: !done });
  const cancel = useCancelTask(cid, taskId);
  const toast = useToast();
  const [stopping, setStopping] = useState(false);

  const streamStatus = (() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === "status_change") return events[i].payload.to as TaskStatus;
    }
    return null;
  })();
  const status = (streamStatus ?? taskQ.data?.status ?? initialStatus ?? "running") as TaskStatus;
  const terminal = isTerminal(status);

  useEffect(() => {
    if (terminal) {
      setDone(true);
      taskQ.refetch();
      // A task reaching a terminal status can flip its session's "busy" flag
      // and its place in the recent-tasks list — neither is invalidated by
      // anything else (the SSE stream that reports completion bypasses React
      // Query entirely), so without this the picker's busy badge freezes at
      // whatever it was when the task started.
      qc.invalidateQueries({ queryKey: keys.tasks(cid) });
      qc.invalidateQueries({ queryKey: keys.sessions(cid) });
    }
  }, [terminal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    onContentChange?.();
  }, [events.length, terminal]); // eslint-disable-line react-hooks/exhaustive-deps

  const lastTool = (() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === "tool_call") return events[i].payload.name as string;
    }
    return null;
  })();
  const result = taskQ.data?.result as { output?: unknown } | null | undefined;
  const errorMsg = taskQ.data?.error?.message;
  const failed = isFailed(status);

  // Graceful stop: request cancellation (the driver SIGTERMs the child so the
  // current step winds down — never a force-kill) and show an optimistic
  // "Stopping…" until the stream reports the terminal `cancelled` status.
  async function onStop() {
    setStopping(true);
    try {
      await cancel.mutateAsync();
    } catch (err) {
      setStopping(false);
      toast.error("Couldn't stop task", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="chat-asst">
      <span className="glyph" aria-hidden="true"><Icons.Bot w={17} /></span>
      <div className="chat-asst-body">
        <ChatTimeline cid={cid} events={events} result={terminal ? result?.output : undefined} />

        {!terminal && (
          <span className="chat-status">
            <span className="spin" />
            {conn === "reconnecting" ? "Reconnecting…" : lastTool ? `Using ${lastTool}` : "Thinking…"}
          </span>
        )}
        {failed && (
          <span className="chat-status" style={{ color: "var(--err-700)" }}>
            <Icons.Warn w={13} /> {status}{errorMsg ? `: ${errorMsg}` : ""}
          </span>
        )}

        <div className="chat-meta">
          <TaskBadge status={status} />
          <Link to={`/containers/${cid}/tasks/${taskId}`}>Open full view →</Link>
          {!terminal && (
            stopping ? (
              <span className="chat-stop pending" aria-live="polite">
                <span className="spin" /> Stopping…
              </span>
            ) : (
              <button
                type="button"
                className="chat-stop"
                onClick={onStop}
                title="Stops gracefully after the current step. Tokens used so far are billed."
              >
                <Icons.Stop w={12} /> Stop
              </button>
            )
          )}
        </div>
      </div>
    </div>
  );
}

// Historical turn: already finished when the thread loaded. Replays its stored
// events for the transcript, falling back to the task's stored result when no
// events were persisted.
function HistoricalTurnBody({ cid, taskId, status, onContentChange }: { cid: string; taskId: string; status: TaskStatus; onContentChange?: () => void }) {
  const failed = isFailed(status);
  const eventsQ = useTaskEvents(cid, taskId);
  const detailQ = useTask(cid, taskId);
  const events = eventsQ.data?.events ?? [];

  const result = detailQ.data?.result as { output?: unknown } | null | undefined;
  const errorMsg = detailQ.data?.error?.message;
  const loading = eventsQ.isLoading || detailQ.isLoading;
  const empty = !loading && events.length === 0 && result?.output == null;

  // The stored transcript loads async and grows the thread — notify the parent
  // so it can keep the view pinned to the bottom while history fills in.
  useEffect(() => { onContentChange?.(); }, [events.length, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="chat-asst">
      <span className="glyph" aria-hidden="true"><Icons.Bot w={17} /></span>
      <div className="chat-asst-body">
        <ChatTimeline cid={cid} events={events} result={result?.output} />

        {loading && <span className="chat-status"><span className="spin" /> Loading…</span>}
        {failed && (
          <span className="chat-status" style={{ color: "var(--err-700)" }}>
            <Icons.Warn w={13} /> {status}{errorMsg ? `: ${errorMsg}` : ""}
          </span>
        )}
        {empty && !failed && (
          <span className="chat-status">No transcript stored. Open the full view for details.</span>
        )}

        <div className="chat-meta">
          <TaskBadge status={status} />
          <Link to={`/containers/${cid}/tasks/${taskId}`}>Open full view →</Link>
        </div>
      </div>
    </div>
  );
}

// One conversational exchange: the user's prompt followed by the agent's
// response. Streams live for running tasks; replays stored events for finished
// ones — both render the ordered transcript inline.
export function ChatTurn({
  cid, taskId, prompt, initialStatus, onContentChange,
}: {
  cid: string; taskId: string; prompt: string; initialStatus?: TaskStatus; onContentChange?: () => void;
}) {
  const [historical] = useState(() => isTerminal(initialStatus));
  return (
    <div className="chat-turn">
      <div className="chat-row user">
        <div className="chat-bubble">{prompt}</div>
      </div>
      {historical
        ? <HistoricalTurnBody cid={cid} taskId={taskId} status={initialStatus as TaskStatus} onContentChange={onContentChange} />
        : <ActiveTurnBody cid={cid} taskId={taskId} initialStatus={initialStatus} onContentChange={onContentChange} />}
    </div>
  );
}
