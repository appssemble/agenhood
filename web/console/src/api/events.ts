import type { Event } from "./types";
import { logStart, logUpdate, logEnd } from "../apiLog/store";
import { API_BASE as BASE } from "./base";

export interface SubscribeOpts {
  onEvent: (e: Event) => void;
  onError: (e: unknown) => void;
  onOpen?: () => void;
  afterSeq?: number;
}

// Opens an SSE stream for a task. Resumes from afterSeq when provided (§4.6).
// Returns an unsubscribe function. EventSource sends the session cookie (same-origin).
export function subscribeEvents(cid: string, tid: string, opts: SubscribeOpts): () => void {
  const path = `/v1/containers/${cid}/tasks/${tid}/events`;
  let url = `${BASE}${path}`;
  if (opts.afterSeq != null) url += `?after_seq=${opts.afterSeq}`;

  let logId = "";
  try {
    logId = logStart({ kind: "sse", method: "SSE", path, sse: { events: 0, closed: false } });
  } catch { /* logging must never break the stream */ }
  let count = 0;

  const src = new EventSource(url, { withCredentials: true });
  src.onopen = () => {
    logUpdate(logId, { ok: true });
    opts.onOpen?.();
  };
  src.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data) as Event;
      count += 1;
      logUpdate(logId, { ok: true, sse: { events: count, closed: false } });
      opts.onEvent(ev);
    } catch { /* ignore malformed frame */ }
  };
  src.onerror = (e) => {
    logUpdate(logId, { ok: false });
    opts.onError(e);
  };

  return () => {
    src.close();
    logEnd(logId, { sse: { events: count, closed: true } });
  };
}
