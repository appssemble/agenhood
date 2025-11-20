export type Bucket = "recent" | "stale" | "never";

export function freshness(
  lastUsed: string | null,
  now = new Date(),
): { bucket: Bucket; tone: "running" | "warn"; label: string } {
  if (!lastUsed) return { bucket: "never", tone: "warn", label: "never used" };
  const days = (now.getTime() - Date.parse(lastUsed)) / 86_400_000;
  if (days <= 7) return { bucket: "recent", tone: "running", label: "recently used" };
  return { bucket: "stale", tone: "warn", label: "stale" };
}
