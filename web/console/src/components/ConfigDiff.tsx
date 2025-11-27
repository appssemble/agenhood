import { diffConfig } from "../lib/diffConfig";
import type { AgentConfig } from "../api/types";
import type { DiffState } from "../lib/diffConfig";

function rowClass(state: DiffState): string {
  return `diff-row ${state}`;
}

export function ConfigDiff({ snapshot, current }: { snapshot: AgentConfig; current: AgentConfig }) {
  const rows = diffConfig(snapshot, current);
  const diffCount = rows.filter((r) => r.state !== "same").length;

  return (
    <div className="mt-2">
      {diffCount > 0 && (
        <div className="mb-2 flex items-center gap-2">
          <span className="pill pill-warn">
            <span className="dot" />
            {diffCount} {diffCount === 1 ? "difference" : "differences"}
          </span>
        </div>
      )}
      <div className="card flush" style={{ borderRadius: 12 }}>
        {/* Header row */}
        <div
          className="diff-row"
          style={{
            background: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: ".08em",
            fontWeight: 700,
          }}
        >
          <span className="k">Field</span>
          <span>Snapshot · ran with</span>
          <span>Current</span>
        </div>
        {rows.map((r) => (
          <div key={r.key} className={rowClass(r.state)}>
            <span className="k">{r.key}</span>
            <span>
              <span className="val was">{r.was}</span>
            </span>
            <span>
              <span className="val now">{r.now}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
