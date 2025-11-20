import { describe, it, expect } from "vitest";
import { deriveStats } from "./containerStats";
import type { TaskSummary } from "../api/types";

const NOW = new Date("2026-06-29T12:00:00Z");

function task(o: Partial<TaskSummary>): TaskSummary {
  return {
    task_id: "t",
    status: "completed",
    prompt: "p",
    started_at: NOW.toISOString(),
    ended_at: null,
    tokens_in: 0,
    tokens_out: 0,
    iterations_used: 0,
    ...o,
  };
}

describe("deriveStats", () => {
  it("counts running + pending as in-flight", () => {
    const s = deriveStats(
      [
        task({ status: "running" }),
        task({ status: "pending" }),
        task({ status: "completed" }),
      ],
      NOW,
    );
    expect(s.running).toBe(2);
  });

  it("does not count failed/cancelled/timed_out as running", () => {
    const s = deriveStats(
      [
        task({ status: "failed" }),
        task({ status: "cancelled" }),
        task({ status: "timed_out" }),
      ],
      NOW,
    );
    expect(s.running).toBe(0);
  });

  it("sums today's tokens only", () => {
    const s = deriveStats(
      [
        task({ started_at: NOW.toISOString(), tokens_in: 10, tokens_out: 3 }),
        // yesterday → excluded
        task({ started_at: "2026-06-28T12:00:00Z", tokens_in: 99, tokens_out: 99 }),
      ],
      NOW,
    );
    expect(s.tokensToday).toBe(13);
  });

  it("covers the || 0 fallback for zero-token tasks counted today", () => {
    // tokens_in=0 and tokens_out=0 trigger the `|| 0` right branch in the
    // expression (t.tokens_in || 0) + (t.tokens_out || 0)
    const s = deriveStats([task({ tokens_in: 0, tokens_out: 0 })], NOW);
    expect(s.tokensToday).toBe(0);
  });

  it("returns zeros for an empty task list", () => {
    const s = deriveStats([], NOW);
    expect(s.running).toBe(0);
    expect(s.tokensToday).toBe(0);
  });
});
