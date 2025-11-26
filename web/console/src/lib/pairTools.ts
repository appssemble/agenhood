import type { Event } from "../api/types";
export interface ToolPair {
  toolUseId: string; name: string; input: unknown;
  ok: boolean | null; content: string | null; durationMs: number | null; seq: number;
}
export function pairToolEvents(events: Event[]): ToolPair[] {
  const byId = new Map<string, ToolPair>();
  const order: string[] = [];
  for (const e of events) {
    const p = e.payload as Record<string, any>;
    if (e.type === "tool_call") {
      byId.set(p.tool_use_id, { toolUseId: p.tool_use_id, name: p.name, input: p.input, ok: null, content: null, durationMs: null, seq: e.seq });
      order.push(p.tool_use_id);
    } else if (e.type === "tool_result") {
      const pair = byId.get(p.tool_use_id);
      if (pair) { pair.ok = !!p.ok; pair.content = p.content ?? null; pair.durationMs = p.duration_ms ?? null; }
    }
  }
  return order.map((id) => byId.get(id)!);
}
