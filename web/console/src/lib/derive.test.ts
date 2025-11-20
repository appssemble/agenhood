import { sortByRecency } from "./recents";
import { deriveStats } from "./containerStats";
import type { Container, TaskSummary } from "../api/types";

test("sortByRecency: newest last_task_at first, nulls last", () => {
  const c = (id: string, t: string | null) => ({ id, last_task_at: t } as Container);
  const out = sortByRecency([c("a", null), c("b", "2026-06-01T00:00:00Z"), c("c", "2026-06-02T00:00:00Z")]);
  expect(out.map((x) => x.id)).toEqual(["c", "b", "a"]);
});

test("deriveStats: running count + today's tokens", () => {
  const today = "2026-06-02T10:00:00Z";
  const tasks = [
    { status: "running", tokens_in: 10, tokens_out: 5, started_at: today },
    { status: "completed", tokens_in: 100, tokens_out: 50, started_at: today },
    { status: "completed", tokens_in: 999, tokens_out: 1, started_at: "2026-05-01T00:00:00Z" },
  ] as TaskSummary[];
  const s = deriveStats(tasks, new Date("2026-06-02T12:00:00Z"));
  expect(s.running).toBe(1);
  expect(s.tokensToday).toBe(165);
});
