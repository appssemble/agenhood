import { useEffect, useRef, useState } from "react";
import { subscribeEvents } from "./events";
import type { Event } from "./types";

export type Conn = "connecting" | "live" | "reconnecting";

// Accumulates a task's SSE event stream. Extracted from TaskViewer so the chat
// layout can stream a turn's events independently. Subscribes only while
// `enabled` (callers pass `!terminal`); resumes from the last seen seq on
// reconnect and dedupes by seq.
export function useTaskStream(cid: string, tid: string, opts?: { enabled?: boolean }) {
  const enabled = opts?.enabled ?? true;
  const [events, setEvents] = useState<Event[]>([]);
  const [conn, setConn] = useState<Conn>("connecting");
  const [tokens, setTokens] = useState(0);
  const lastSeq = useRef(0);

  useEffect(() => {
    if (!cid || !tid || !enabled) return;
    setConn("connecting");
    const stop = subscribeEvents(cid, tid, {
      afterSeq: lastSeq.current || undefined,
      onOpen: () => setConn("live"),
      onEvent: (e) => {
        setConn("live");
        lastSeq.current = e.seq;
        setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e]));
        if (e.type === "token_update") {
          setTokens((e.payload.tokens_in as number) + (e.payload.tokens_out as number));
        }
      },
      onError: () => setConn("reconnecting"),
    });
    return stop;
  }, [cid, tid, enabled]);

  return { events, conn, tokens };
}
