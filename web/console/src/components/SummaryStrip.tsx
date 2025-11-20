import type { Container } from "../api/types";

function statusPill(status: string, transitionTo?: string | null) {
  if (transitionTo) {
    return <span className="pill pill-trans"><span className="spin" /> {transitionTo}</span>;
  }
  if (status === "running") {
    return <span className="pill pill-running"><span className="dot" /> running</span>;
  }
  if (status === "error") {
    return <span className="pill pill-error"><span className="dot" /> error</span>;
  }
  return <span className="pill pill-dormant"><span className="dot" /> {status}</span>;
}

export function SummaryStrip({ container, running, tokensToday, actions }: {
  container: Container; running: number; tokensToday: number; actions?: React.ReactNode;
}) {
  const transitioning =
    container.status === "provisioning" ||
    container.status === "resuming" ||
    container.status === "pausing" ||
    container.status === "archiving" ||
    container.status === "recovering" ||
    container.status === "destroying"
      ? container.status
      : null;

  return (
    <div className="summary-strip">
      <div className="stack title-stack">
        <span className="name">{container.name}</span>
        <span className="id" style={{ fontSize: 11.5 }}>{container.external_id ?? container.id}</span>
      </div>
      <div className="sep" />
      {statusPill(container.status, transitioning)}
      <div className="sep" />
      <div className="stack">
        <span className="lab">Driver / Model</span>
        <span className="val mono" style={{ fontSize: 12 }}>{container.config.driver} · {container.config.model}</span>
      </div>
      <div className="sep" />
      <div className="stack">
        <span className="lab">Variant</span>
        <span className="val mono" style={{ fontSize: 12 }}>{container.image_variant}</span>
      </div>
      <div className="sep" />
      <div className="stack">
        <span className="lab">Tokens · today</span>
        <span className="val num">{tokensToday.toLocaleString()}</span>
      </div>
      <div className="sep" />
      <div className="stack">
        <span className="lab">Tasks running</span>
        <span className="val num">{running}</span>
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
