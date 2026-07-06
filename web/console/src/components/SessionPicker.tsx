import { useState } from "react";
import { useSessions } from "../api/queries";
import { newSessionId } from "../lib/sessions";

export function SessionPicker({
  cid,
  sessionId,
  onChange,
}: {
  cid: string;
  sessionId: string | null;
  onChange: (sessionId: string | null) => void;
}) {
  const sessionsQ = useSessions(cid);
  const [open, setOpen] = useState(false);

  const current = sessionsQ.data?.sessions.find((s) => s.session_id === sessionId);
  const label = sessionId ? (current ? sessionId : `${sessionId} (new)`) : "No session";

  return (
    <div className="session-picker" style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <div role="menu" className="session-picker-menu" style={{ position: "absolute", zIndex: 10 }}>
          <button
            type="button"
            role="menuitem"
            onClick={() => { onChange(null); setOpen(false); }}
          >
            No session
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => { onChange(newSessionId()); setOpen(false); }}
          >
            New session
          </button>
          {(sessionsQ.data?.sessions ?? []).map((s) => (
            <button
              key={s.session_id}
              type="button"
              role="menuitem"
              onClick={() => { onChange(s.session_id); setOpen(false); }}
            >
              {s.session_id} · {s.driver} · {s.task_count} task{s.task_count === 1 ? "" : "s"}
              {s.busy ? " · busy" : ""}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
