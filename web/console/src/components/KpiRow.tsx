import { formatCompact } from "../lib/format";

export interface KpiTotals {
  tokens: number;
  tasks: number;
  successRate: number | null;
  iterations: number;
}

function Kpi({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, letterSpacing: ".08em",
        textTransform: "uppercase", color: "var(--muted-2)" }}>{label}</span>
      <span data-testid={id} className="num"
        style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
        {value}
      </span>
    </div>
  );
}

export function KpiRow({ totals }: { totals: KpiTotals }) {
  const success = totals.successRate === null ? "—" : `${Math.round(totals.successRate * 100)}%`;
  return (
    <div style={{ display: "flex", gap: 40, flexWrap: "wrap" }}>
      <Kpi id="kpi-tokens" label="Tokens" value={formatCompact(totals.tokens)} />
      <Kpi id="kpi-tasks" label="Tasks" value={totals.tasks.toLocaleString()} />
      <Kpi id="kpi-success" label="Success" value={success} />
      <Kpi id="kpi-iterations" label="Iterations" value={totals.iterations.toLocaleString()} />
    </div>
  );
}
