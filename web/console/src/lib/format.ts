export function formatCompact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (abs >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(Math.round(n));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatOptionalBytes(bytes?: number | null): string | null {
  return bytes == null ? null : formatBytes(bytes);
}

/** Compact form of a long prefixed id (e.g. "prm_01jyk8abcd…wxyz") for tight
 *  UIs: keeps the readable prefix and a distinguishing tail. The full id stays
 *  available via copy/tooltip. Short ids (≤12 chars) are returned unchanged. */
export function shortId(id: string): string {
  if (!id || id.length <= 12) return id;
  return `${id.slice(0, 7)}…${id.slice(-3)}`;
}

/** Human-readable calendar date, e.g. "Jun 14, 2026". Falls back gracefully on
 *  null ("—") or unparseable input (returned verbatim). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Compact short date + time, e.g. "Jun 30, 09:00". null/unparseable → "—". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Compact relative time, past OR future: "3h ago" / "in 3h" / "just now".
 *  null/unparseable → "—". `nowMs` is passed in for deterministic rendering. */
export function relativeFromNow(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const past = t <= nowMs;
  const s = Math.floor(Math.abs(t - nowMs) / 1000);
  if (s < 60) return past ? "just now" : "in <1m";
  const m = Math.floor(s / 60);
  if (m < 60) return past ? `${m}m ago` : `in ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return past ? `${h}h ago` : `in ${h}h`;
  const d = Math.floor(h / 24);
  return past ? `${d}d ago` : `in ${d}d`;
}

/** Elapsed time, at the coarsest unit that still reads precisely: "312ms",
 *  "1.4s", "2m 13s", "1h 04m". Each branch decides using the value *as it
 *  will be rounded*, so no boundary can render as "60.0s" or "60m".
 *  Negative or non-finite input → "—". */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)}s`;
  const sec = Math.round(ms / 1000);
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const min = Math.round(ms / 60_000);
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, "0")}m`;
}
