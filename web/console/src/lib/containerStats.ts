import type { TaskSummary } from "../api/types";

export function deriveStats(tasks: TaskSummary[], now = new Date()) {
  const sameDay = (iso: string | null) =>
    !!iso && new Date(iso).toDateString() === now.toDateString();
  let running = 0, tokensToday = 0;
  for (const t of tasks) {
    if (t.status === "running" || t.status === "pending") running++;
    if (sameDay(t.started_at)) tokensToday += (t.tokens_in || 0) + (t.tokens_out || 0);
  }
  return { running, tokensToday };
}
