import { Link } from "react-router-dom";
import type { BreakdownGroup } from "../api/types";
import { formatCompact } from "../lib/format";
import { EmptyState } from "../ui/EmptyState";

const total = (g: BreakdownGroup) => g.tokens_in + g.tokens_out;

export function TopContainers({ groups, limit = 5 }: { groups: BreakdownGroup[]; limit?: number }) {
  const ranked = [...groups].sort((a, b) => total(b) - total(a)).slice(0, limit);
  if (ranked.length === 0) {
    return (
      <EmptyState
        size="sm"
        icon="Container"
        title="No usage in this range"
        description="Run a task or widen the time range to see usage."
      />
    );
  }
  const max = total(ranked[0]) || 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {ranked.map((g, i) => (
        <div key={g.key} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <Link to={`/containers/${g.key}`} data-testid="lb-name"
              style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-2)", textDecoration: "none" }}>
              {g.label}
            </Link>
            <span className="num" style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, fontWeight: 600 }}>
              {formatCompact(total(g))}
            </span>
          </div>
          <div style={{ height: 8, background: "var(--surface-2)", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ height: "100%", borderRadius: 999,
              width: `${(total(g) / max) * 100}%`,
              background: i === 0 ? "var(--p-300)" : "var(--p-200)" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
