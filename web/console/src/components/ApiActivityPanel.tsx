import { memo, useEffect, useMemo, useState } from "react";
import { useApiLog, useApiLogCount, clearLog } from "../apiLog/store";
import { toCurl, isSessionOnly } from "../apiLog/curl";
import type { ApiLogEntry } from "../apiLog/types";
import { Icons } from "../ui/Icon";
import { EmptyState } from "../ui/EmptyState";

function verbClass(method: string): string {
  const m = method.toLowerCase();
  if (m === "sse") return "v-sse";
  if (m === "get") return "v-get";
  if (m === "post") return "v-post";
  if (m === "patch" || m === "put") return "v-patch";
  if (m === "delete") return "v-del";
  return "v-get";
}

function statusLabel(e: ApiLogEntry): string {
  if (e.kind === "sse") return e.sse?.closed ? "closed" : "open";
  if (e.status === undefined) return e.error ? "error" : "…";
  return String(e.status);
}

function pretty(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function copy(text: string): void {
  navigator.clipboard?.writeText(text).catch(() => {});
}

const Detail = memo(function Detail({ entry }: { entry: ApiLogEntry }) {
  const origin = window.location.origin;
  const curl = useMemo(
    () => toCurl({ method: entry.method, path: entry.path, requestBody: entry.requestBody }, origin),
    [entry.method, entry.path, entry.requestBody, origin],
  );
  const sessionOnly = entry.sessionOnly ?? isSessionOnly(entry.path);
  const reqPretty = useMemo(() => pretty(entry.requestBody), [entry.requestBody]);
  const respPretty = useMemo(() => pretty(entry.responseBody), [entry.responseBody]);

  return (
    <div className="fc-apilog-detail">
      {entry.requestBody !== undefined && (
        <>
          <div className="fc-apilog-label">Request body</div>
          <pre className="fc-apilog-code">{reqPretty}</pre>
        </>
      )}

      {entry.kind === "rest" && (
        <>
          <div className="fc-apilog-label">cURL (public API, with your API key)</div>
          <div className="fc-apilog-note">
            {sessionOnly
              ? "Session-only endpoint. The console uses your session cookie; this is not callable with an API key."
              : "The console uses your session cookie; this is the equivalent public-API call you'd make with an API key."}
          </div>
          <pre className="fc-apilog-code">{curl}</pre>
          <div className="fc-apilog-copybar">
            <button type="button" className="fc-apilog-mini dark" onClick={() => copy(curl)}>Copy cURL</button>
            {entry.requestBody !== undefined && (
              <button type="button" className="fc-apilog-mini" onClick={() => copy(reqPretty)}>Copy request</button>
            )}
            {entry.responseBody !== undefined && (
              <button type="button" className="fc-apilog-mini" onClick={() => copy(respPretty)}>Copy response</button>
            )}
          </div>
        </>
      )}

      {entry.responseBody !== undefined && (
        <>
          <div className="fc-apilog-label">Response{entry.status ? ` (${entry.status})` : ""}</div>
          <pre className="fc-apilog-code">{respPretty}</pre>
        </>
      )}

      {entry.error && (
        <>
          <div className="fc-apilog-label">Error</div>
          <pre className="fc-apilog-code">{entry.error}</pre>
        </>
      )}
    </div>
  );
});

export function ApiActivityPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const entries = useApiLog();
  const [filter, setFilter] = useState<"all" | "errors">("all");
  const [q, setQ] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);

  if (!open) return null;

  const visible = entries.filter(
    (e) => (filter === "all" || e.ok === false) && (!q || e.path.includes(q)),
  );

  return (
    <aside className="fc-apilog" aria-label="API activity">
        <header className="fc-apilog-head">
          <div className="fc-apilog-title">
            <Icons.Logs /> <span>API Activity</span>
          </div>
          <button type="button" className="fc-apilog-x" aria-label="Close" onClick={onClose}>
            <Icons.Close />
          </button>
        </header>

        <div className="fc-apilog-tools">
          <button type="button" className={"fc-apilog-chip" + (filter === "all" ? " on" : "")} onClick={() => setFilter("all")}>All</button>
          <button type="button" className={"fc-apilog-chip" + (filter === "errors" ? " on" : "")} onClick={() => setFilter("errors")}>Errors</button>
          <input autoFocus className="fc-apilog-filter" placeholder="Filter path…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="button" className="fc-apilog-clear" onClick={() => clearLog()}>Clear</button>
        </div>

        <div className="fc-apilog-list">
          {visible.length === 0 && (
            <EmptyState
              size="sm"
              icon="Logs"
              title={entries.length === 0 ? "No API calls yet" : "No matching calls"}
              description={
                entries.length === 0
                  ? "Requests to the agenhood API are logged here as you use the console."
                  : undefined
              }
            />
          )}
          {visible.map((e) => {
            const isOpen = expanded === e.id;
            return (
              <div key={e.id} className="fc-apilog-item">
                <button
                  type="button"
                  className={"fc-apilog-row" + (e.ok === false ? " err" : "")}
                  aria-expanded={isOpen}
                  onClick={() => setExpanded(isOpen ? null : e.id)}
                >
                  <span className={"fc-apilog-verb " + verbClass(e.method)}>{e.method}</span>
                  <span className="fc-apilog-path">{e.path}</span>
                  {e.sessionOnly && <span className="fc-apilog-tag">session</span>}
                  <span className="fc-apilog-status">{statusLabel(e)}</span>
                  <span className="fc-apilog-dur">
                    {e.kind === "sse" ? `${e.sse?.events ?? 0} ev` : e.durationMs != null ? `${e.durationMs}ms` : ""}
                  </span>
                </button>
                {isOpen && <Detail entry={e} />}
              </div>
            );
          })}
        </div>
    </aside>
  );
}

export function ApiActivityButton({ onClick, active = false }: { onClick: () => void; active?: boolean }) {
  const count = useApiLogCount();
  return (
    <button
      type="button"
      className={"fc-apilog-btn" + (active ? " active" : "")}
      aria-label="API activity"
      aria-pressed={active}
      onClick={onClick}
    >
      <Icons.Logs />
      {count > 0 && <span className="fc-apilog-count">{count}</span>}
    </button>
  );
}
