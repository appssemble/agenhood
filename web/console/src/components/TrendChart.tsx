import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";
import type { UsageSeriesPoint } from "../api/types";
import { formatCompact } from "../lib/format";

const IN = "var(--p-400)";
const OUT = "var(--ink)";

function bucketLabel(iso: string, interval: "hour" | "day"): string {
  const d = new Date(iso);
  return interval === "hour"
    ? `${String(d.getUTCHours()).padStart(2, "0")}:00`
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

function ChartTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: "var(--r-2)", boxShadow: "var(--sh-2)",
      padding: "9px 11px", minWidth: 140,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink)",
        letterSpacing: "-0.01em", marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {payload.map((entry) => (
          <div key={String(entry.name)} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 9, height: 9, borderRadius: 3, flex: "0 0 9px",
              background: entry.color }} />
            <span style={{ fontSize: 11.5, color: "var(--muted)" }}>{entry.name}</span>
            <span className="num" style={{ marginLeft: "auto", fontFamily: "var(--font-mono)",
              fontSize: 11.5, fontWeight: 600, color: "var(--ink)" }}>
              {formatCompact(Number(entry.value))}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6,
      fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--muted)" }}>
      <span style={{ width: 11, height: 11, borderRadius: 3, background: color }} />
      {label}
    </span>
  );
}

export function TrendChart({ series, interval }: {
  series: UsageSeriesPoint[]; interval: "hour" | "day";
}) {
  const data = series.map((p) => ({
    label: bucketLabel(p.start, interval),
    "tokens in": p.tokens_in,
    "tokens out": p.tokens_out,
  }));
  // Scale bar width to bucket count so sparse (daily) ranges stay substantial
  // and dense (hourly) ranges stay slim instead of crowding.
  const n = data.length;
  const barSize = n <= 8 ? 34 : n <= 12 ? 24 : n <= 18 ? 16 : 11;
  return (
    <div>
      <div style={{ display: "flex", gap: 16, marginBottom: 8 }}>
        <Swatch color={IN} label="tokens in" />
        <Swatch color={OUT} label="tokens out" />
      </div>
      <div data-testid="trend-chart" style={{ width: "100%", height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}
            barGap={0} barCategoryGap="22%">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tickLine={false} axisLine={false}
              tick={{ fill: "var(--muted)", fontSize: 11 }} dy={2} />
            <YAxis tickFormatter={formatCompact} tickLine={false} axisLine={false} width={44}
              tick={{ fill: "var(--muted)", fontSize: 11 }} />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ fill: "var(--ink)", fillOpacity: 0.05, radius: 6 }}
              wrapperStyle={{ outline: "none" }}
              animationDuration={140}
            />
            <Bar dataKey="tokens in" fill={IN} radius={[2, 2, 0, 0]} maxBarSize={barSize} />
            <Bar dataKey="tokens out" fill={OUT} radius={[2, 2, 0, 0]} maxBarSize={barSize} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
