import type { Event } from "../api/types";
import { containerFileRawUrl } from "../api/fileUrls";

function downloadHref(cid: string, path: string) {
  return containerFileRawUrl(cid, path);
}

// Map event type to feed-row class modifier
function rowClass(type: string): string {
  if (type === "assistant_message") return "assistant";
  if (type === "tool_call" || type === "tool_result") return "tool";
  if (type === "log") return "log";
  if (type === "task_started" || type === "status_change") return "status";
  return "";
}

// Renders the per-event body content — verbatim from the original EventRow logic.
// Content must stay byte-for-byte identical so test text assertions keep passing.
function EventBody({ cid, ev }: { cid: string; ev: Event }) {
  const p = ev.payload as Record<string, any>;
  switch (ev.type) {
    case "task_started":
      return <span>driver <b>{p.driver}</b> · model <b>{p.model}</b></span>;
    case "assistant_message": {
      const text = (p.content as any[] | undefined)
        ?.filter((b) => b.type === "text")
        .map((b) => b.text)
        .join("\n");
      return <span>{text}</span>;
    }
    case "tool_call":
      return (
        <span>
          <span className="mono font-semibold">{p.name}</span>{" "}
          <span className="mono text-muted">{JSON.stringify(p.input)}</span>
        </span>
      );
    case "tool_result":
      return <span>{p.ok ? "ok" : "error"} · {p.duration_ms} ms</span>;
    case "token_update":
      return <span>tokens in {p.tokens_in} · out {p.tokens_out}</span>;
    case "file_changed":
      return (
        <span>
          {p.operation}{" "}
          <a className="underline" href={downloadHref(cid, p.path)}>{p.path}</a>
          {" "}· {p.size} B
        </span>
      );
    case "iteration_started":
      return <span>iteration {p.iteration}</span>;
    case "status_change":
      return <span>{p.from} → {p.to}</span>;
    case "log":
      return (
        <span className={p.level === "warn" ? "text-warn-700" : ""}>{p.message}</span>
      );
    case "opencode_stdout":
      return <span className="mono">{p.line}</span>;
    case "opencode_event":
      return <span className="mono">{JSON.stringify(p.raw)}</span>;
    case "codex_stdout":
      return <span className="mono">{p.line}</span>;
    case "codex_event":
      return <span className="mono">{JSON.stringify(p.raw)}</span>;
    case "claude_stdout":
      return <span className="mono">{p.line}</span>;
    case "claude_event":
      return <span className="mono">{JSON.stringify(p.raw)}</span>;
    default:
      return null;
  }
}

export function EventFeed({ events, cid }: { events: Event[]; cid: string }) {
  return (
    <div>
      {events.map((ev) => {
        const label = ev.type.replace("_", " ");
        const modifier = rowClass(ev.type);
        return (
          <div
            key={ev.seq}
            data-testid="event-row"
            data-type={ev.type}
            className={`feed-row${modifier ? ` ${modifier}` : ""}`}
          >
            <span className="gut"><span className="marker" /></span>
            <div className="body">
              <div className="lab">{label}</div>
              <div className="txt">
                <EventBody cid={cid} ev={ev} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
