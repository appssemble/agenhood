import { useCallback, useState } from "react";
const KEY = "ah.pins";
function read(): string[] { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } }

export function usePins() {
  const [pins, setPins] = useState<string[]>(read);
  const toggle = useCallback((id: string) => {
    setPins((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem(KEY, JSON.stringify(next));
      return next;
    });
  }, []);
  return { pins, isPinned: (id: string) => pins.includes(id), toggle };
}
