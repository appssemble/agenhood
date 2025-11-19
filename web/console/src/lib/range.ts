export const RANGES = ["24h", "7d", "30d"] as const;
export type Range = (typeof RANGES)[number];

export interface RangeParams {
  from: string;
  to: string;
  interval: "hour" | "day";
}

const SPEC: Record<Range, { ms: number; interval: "hour" | "day" }> = {
  "24h": { ms: 24 * 60 * 60 * 1000, interval: "hour" },
  "7d": { ms: 7 * 24 * 60 * 60 * 1000, interval: "day" },
  "30d": { ms: 30 * 24 * 60 * 60 * 1000, interval: "day" },
};

export function rangeToParams(range: Range, now: Date = new Date()): RangeParams {
  const { ms, interval } = SPEC[range];
  const to = now.toISOString();
  const from = new Date(now.getTime() - ms).toISOString();
  return { from, to, interval };
}

export function isRange(v: string | null): v is Range {
  return v !== null && (RANGES as readonly string[]).includes(v);
}
