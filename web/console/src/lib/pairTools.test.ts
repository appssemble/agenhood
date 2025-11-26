import { pairToolEvents } from "./pairTools";
import type { Event } from "../api/types";

const ev = (seq: number, type: Event["type"], payload: any): Event => ({ seq, type, ts: "", payload });

test("links tool_result to its tool_call by tool_use_id", () => {
  const events = [
    ev(1, "tool_call", { tool_use_id: "tu_1", name: "web_fetch", input: { url: "x" } }),
    ev(2, "tool_result", { tool_use_id: "tu_1", ok: true, content: "200", duration_ms: 1420 }),
  ];
  const pairs = pairToolEvents(events);
  expect(pairs).toHaveLength(1);
  expect(pairs[0].name).toBe("web_fetch");
  expect(pairs[0].ok).toBe(true);
  expect(pairs[0].durationMs).toBe(1420);
});

test("a call without a result yet is pending", () => {
  const pairs = pairToolEvents([ev(1, "tool_call", { tool_use_id: "tu_2", name: "bash", input: {} })]);
  expect(pairs[0].ok).toBeNull();
});
