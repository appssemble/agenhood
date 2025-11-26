import type { AgentConfig } from "../api/types";
export type DiffState = "same" | "changed" | "added" | "removed";
export interface DiffRow { key: string; was: string; now: string; state: DiffState; }

export function diffConfig(snap: AgentConfig, cur: AgentConfig): DiffRow[] {
  const rows: DiffRow[] = [];
  const cmp = (key: string, was: string, now: string) =>
    rows.push({ key, was, now, state: was === now ? "same" : "changed" });
  cmp("Driver", snap.driver, cur.driver);
  cmp("Model", snap.model, cur.model);
  cmp("Prompt mode", snap.system_prompt_mode, cur.system_prompt_mode);
  cmp("System prompt", snap.system_prompt === cur.system_prompt ? "(unchanged)" : "(was)", snap.system_prompt === cur.system_prompt ? "(unchanged)" : "(now)");
  const tools = new Set([...snap.tools, ...cur.tools]);
  for (const t of [...tools].sort()) {
    const inS = snap.tools.includes(t), inC = cur.tools.includes(t);
    if (inS && inC) continue;
    rows.push({ key: `Tools · ${t}`, was: inS ? "enabled" : "—", now: inC ? "enabled" : "—", state: inC ? "added" : "removed" });
  }
  return rows;
}
