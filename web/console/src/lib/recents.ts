import type { Container } from "../api/types";
export function sortByRecency(cs: Container[]): Container[] {
  return [...cs].sort((a, b) => {
    const ta = a.last_task_at ? Date.parse(a.last_task_at) : -Infinity;
    const tb = b.last_task_at ? Date.parse(b.last_task_at) : -Infinity;
    return tb - ta;
  });
}
