import { useEffect, useRef, useState } from "react";
import { useSessions } from "../api/queries";
import { newSessionId } from "../lib/sessions";
import { Icons } from "../ui/Icon";
import { Pill } from "../ui/Pill";

// Real ids are `sess_<uuid>` — show a short, git-SHA-style tag so rows and the
// trigger stay compact. Short test-fixture ids (e.g. "sess-1") pass through
// unchanged since they don't carry the "sess_" prefix.
function shortId(id: string): string {
  return id.startsWith("sess_") ? id.slice(5, 13) : id;
}

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
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape — same pattern as TenantSwitcher.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const sessions = sessionsQ.data?.sessions ?? [];
  const current = sessions.find((s) => s.session_id === sessionId);
  const label = sessionId
    ? `Session ${shortId(sessionId)}${current ? "" : " (new)"}`
    : "No session";

  function choose(id: string | null) {
    setOpen(false);
    onChange(id);
  }

  return (
    <div className="dd session-picker" ref={rootRef}>
      <button
        type="button"
        className={"select dd-trigger session-picker-trigger" + (open ? " open" : "")}
        aria-haspopup="menu"
        aria-expanded={open}
        title={sessionId ?? undefined}
        onClick={() => setOpen((v) => !v)}
      >
        <Icons.History w={13} />
        <span>{label}</span>
      </button>
      {open && (
        <div role="menu" className="dd-menu session-picker-menu">
          <div className="dd-list session-picker-list">
            <button
              type="button"
              role="menuitem"
              className={"dd-option" + (!sessionId ? " selected" : "")}
              onClick={() => choose(null)}
            >
              <span>No session</span>
              {!sessionId && <Icons.Check w={14} />}
            </button>
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                role="menuitem"
                title={s.session_id}
                className={"dd-option" + (s.session_id === sessionId ? " selected" : "")}
                onClick={() => choose(s.session_id)}
              >
                <span className="session-picker-row">
                  <span className="session-picker-id">Session {shortId(s.session_id)}</span>
                  <span className="session-picker-meta">
                    {s.driver} · {s.task_count} task{s.task_count === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="session-picker-end">
                  {s.busy && (
                    <Pill tone="warn"><span className="dot" />busy</Pill>
                  )}
                  {s.session_id === sessionId && <Icons.Check w={14} />}
                </span>
              </button>
            ))}
            <button
              type="button"
              role="menuitem"
              className="dd-option dd-action"
              onClick={() => choose(newSessionId())}
            >
              <span className="dd-action-plus" aria-hidden="true">+</span>
              <span>New session</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
