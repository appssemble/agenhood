import { Link } from "react-router-dom";
import { Icons } from "../ui/Icon";
import { Sparkline } from "./Sparkline";
import { formatCompact } from "../lib/format";
import type { KpiTotals } from "./KpiRow";
import type { Container, ContainerStatus, UsageSeriesPoint } from "../api/types";

/** Period-over-period change: compare the second half of the series to the
 *  first half. Returns a signed ratio, or null when there isn't enough data. */
function halfDelta(values: number[]): number | null {
  if (values.length < 4) return null;
  const mid = Math.floor(values.length / 2);
  const a = values.slice(0, mid).reduce((s, v) => s + v, 0);
  const b = values.slice(mid).reduce((s, v) => s + v, 0);
  if (a === 0) return b > 0 ? 1 : null;
  return (b - a) / a;
}

function Delta({ value, dark = false }: { value: number | null; dark?: boolean }) {
  if (value === null || !isFinite(value)) return null;
  const up = value >= 0;
  const pct = Math.round(Math.abs(value) * 100);
  if (pct === 0) return null;
  const tone = dark
    ? { color: up ? "var(--p-300)" : "#C9C9C9", bg: "rgba(255,255,255,.08)" }
    : up
      ? { color: "var(--success-700)", bg: "var(--success-100)" }
      : { color: "var(--muted)", bg: "var(--surface-3)" };
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 2,
        fontSize: 11, fontWeight: 700, fontVariantNumeric: "tabular-nums",
        color: tone.color, background: tone.bg, borderRadius: 999, padding: "2px 7px",
      }}
    >
      {up ? <Icons.ArrowUp w={11} /> : <Icons.ArrowDown w={11} />}{pct}%
    </span>
  );
}

const FLEET: { key: ContainerStatus; label: string; color: string }[] = [
  { key: "running", label: "running", color: "var(--p-400)" },
  { key: "paused", label: "paused", color: "var(--neut-500)" },
  { key: "error", label: "error", color: "var(--err-500)" },
  { key: "archived", label: "archived", color: "var(--muted-2)" },
];

export function MetricsBento({
  totals,
  series,
  containers,
}: {
  totals: KpiTotals;
  series: UsageSeriesPoint[];
  containers: Container[];
}) {
  const tokenSeries = series.map((p) => p.tokens_in + p.tokens_out);
  const taskSeries = series.map((p) => p.tasks);
  const iterSeries = series.map((p) => p.iterations);
  const tokensIn = series.reduce((s, p) => s + p.tokens_in, 0);
  const tokensOut = series.reduce((s, p) => s + p.tokens_out, 0);

  // Fleet buckets (anything not in the named set falls under "archived/other").
  const counts: Record<string, number> = {};
  for (const c of containers) {
    const known = FLEET.some((f) => f.key === c.status);
    counts[known ? c.status : "archived"] = (counts[known ? c.status : "archived"] ?? 0) + 1;
  }
  const fleetTotal = containers.length || 1;
  const fleetSegs = FLEET.filter((f) => counts[f.key]);
  const errored = containers.filter((c) => c.status === "error").length;
  const running = counts.running ?? 0;

  const successPct = totals.successRate;
  const successLabel = successPct === null ? "—" : `${Math.round(successPct * 100)}%`;
  const completed = Math.round((successPct ?? 0) * totals.tasks);

  return (
    <div className="bento">
      {/* Hero — total tokens */}
      <div className="tile tile-hero">
        <div className="tile-top">
          <span className="tile-label" style={{ color: "rgba(255,255,255,.65)" }}>
            <Icons.Coins w={13} /> Total tokens
          </span>
          <Delta value={halfDelta(tokenSeries)} dark />
        </div>
        <div className="hero-num">{formatCompact(totals.tokens)}</div>
        <div className="hero-sub">
          <span><b className="num">{formatCompact(tokensIn)}</b> in</span>
          <span style={{ opacity: .5 }}>·</span>
          <span><b className="num">{formatCompact(tokensOut)}</b> out</span>
        </div>
        <div className="hero-spark">
          <Sparkline values={tokenSeries} height={104} stroke="var(--p-300)" fill="rgba(241,233,75,.14)" strokeWidth={2.25} />
        </div>
      </div>

      {/* Success rate */}
      <div className="tile">
        <span className="tile-label"><Icons.Check w={13} /> Success rate</span>
        <div className="stat-num">{successLabel}</div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
          <b className="num" style={{ color: "var(--ink)" }}>{completed}</b> of <span className="num">{totals.tasks.toLocaleString()}</span> completed
        </div>
        <div className="meter" aria-hidden>
          {successPct !== null && (
            <i
              style={{
                width: `${Math.max(0, Math.min(1, successPct)) * 100}%`,
                background: successPct >= 0.5 ? "var(--success-500)" : "var(--p-500)",
              }}
            />
          )}
        </div>
      </div>

      {/* Tasks */}
      <div className="tile">
        <div className="tile-top">
          <span className="tile-label"><Icons.Checklist w={13} /> Tasks</span>
          <Delta value={halfDelta(taskSeries)} />
        </div>
        <div className="stat-num">{totals.tasks.toLocaleString()}</div>
        <div className="tile-spark"><Sparkline values={taskSeries} height={30} /></div>
      </div>

      {/* Iterations */}
      <div className="tile">
        <div className="tile-top">
          <span className="tile-label"><Icons.Refresh w={13} /> Iterations</span>
          <Delta value={halfDelta(iterSeries)} />
        </div>
        <div className="stat-num">{totals.iterations.toLocaleString()}</div>
        <div className="tile-spark"><Sparkline values={iterSeries} height={30} stroke="var(--neut-500)" fill="rgba(122,133,127,.14)" /></div>
      </div>

      {/* Fleet health */}
      <div className="tile">
        <div className="tile-top">
          <span className="tile-label"><Icons.Container w={13} /> Fleet</span>
          <span className="tile-meta">
            <i className="dot" style={{ background: running > 0 ? "var(--p-400)" : "var(--muted-2)" }} />
            <b className="num">{running}</b> live
          </span>
        </div>
        <div className="stat-num" style={{ marginBottom: 8 }}>{containers.length}</div>
        <div className="fleet-bar" aria-hidden>
          {fleetSegs.length === 0
            ? <span style={{ flex: 1, background: "var(--surface-3)" }} />
            : fleetSegs.map((f) => (
                <span key={f.key} style={{ flex: counts[f.key] / fleetTotal, background: f.color }} title={`${counts[f.key]} ${f.label}`} />
              ))}
        </div>
        <div className="fleet-legend">
          {fleetSegs.map((f) => (
            <span key={f.key} className="leg">
              <i className="dot" style={{ background: f.color }} />
              <b>{counts[f.key]}</b> {f.label}
            </span>
          ))}
          {errored > 0 && (
            <Link to="/containers" className="leg" style={{ marginLeft: "auto", color: "var(--err-700)" }}>
              <Icons.Warn w={12} /> resolve
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
