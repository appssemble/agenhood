import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { useContainer } from "../api/queries";
import { consoleWsUrl } from "../lib/consoleSocket";
import { Icons } from "../ui/Icon";

type Status = "idle" | "connecting" | "connected" | "closed";

const CLOSE_MESSAGES: Record<number, string> = {
  4401: "Authentication required.",
  4403: "Forbidden.",
  4404: "Container not found.",
  4409: "Container must be running to open a console.",
  1011: "Could not start the shell.",
};

export default function Console() {
  const { cid } = useParams<{ cid: string }>();
  const isRunning = useContainer(cid!).data?.status === "running";
  const [status, setStatus] = useState<Status>("idle");
  const [note, setNote] = useState<string | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Dispose the terminal and socket and clear refs. Detaches the socket
  // handlers first so a user-initiated close doesn't trigger the onclose note.
  function teardown() {
    const ws = wsRef.current;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      ws.close();
    }
    wsRef.current = null;
    termRef.current?.dispose();
    termRef.current = null;
    fitRef.current = null;
  }

  function disconnect() {
    teardown();
    setStatus("idle");
    setNote(null);
  }

  function connect() {
    if (!cid || !hostRef.current) return;
    teardown(); // never stack a second terminal/socket on top of an old one
    const term = new Terminal({ convertEol: false, cursorBlink: true, fontSize: 13 });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const ws = new WebSocket(consoleWsUrl(cid));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    setStatus("connecting");
    setNote(null);

    ws.onopen = () => {
      setStatus("connected");
      ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };
    ws.onmessage = (e) => {
      const data = e.data;
      if (data instanceof ArrayBuffer) term.write(new Uint8Array(data));
      else if (typeof data === "string") term.write(data);
    };
    ws.onclose = (e) => {
      setStatus("closed");
      if (e.code !== 1000) setNote(CLOSE_MESSAGES[e.code] ?? `Disconnected (${e.code}).`);
    };
    term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d));
    });
  }

  // Tear everything down on unmount / navigate-away.
  useEffect(() => {
    return () => teardown();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!isRunning) {
    return (
      <div className="p-8 text-sm text-muted">
        The container must be running to open a console.
      </div>
    );
  }

  const connected = status === "connected" || status === "connecting";
  const statusLabel =
    status === "connected" ? "connected"
    : status === "connecting" ? "connecting…"
    : "disconnected";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-3)",
      }}
    >
      <div
        style={{
          padding: "10px 18px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 7,
            fontWeight: 700,
            fontSize: 13.5,
          }}
        >
          <Icons.Terminal w={15} /> Console
        </span>
        <span className="id" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            className={status === "connected" ? "fc-cdot running" : "fc-cdot"}
            aria-hidden="true"
          />
          {statusLabel}
        </span>
        {note && (
          <span style={{ color: "var(--danger)", fontSize: 12 }}>{note}</span>
        )}
        <span className="id" style={{ marginLeft: "auto" }}>root@{cid}</span>
        {connected ? (
          <button className="btn btn-secondary btn-sm" type="button" onClick={disconnect}>
            Disconnect
          </button>
        ) : (
          <button className="btn btn-primary btn-sm" type="button" onClick={connect}>
            Connect
          </button>
        )}
      </div>
      <div
        ref={hostRef}
        style={{ flex: 1, minHeight: 0, background: "#000", padding: 8 }}
      />
    </div>
  );
}
