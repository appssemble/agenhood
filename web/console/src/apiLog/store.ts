import { useSyncExternalStore } from "react";
import type { ApiLogEntry } from "./types";

export const CAPACITY = 200;
const STORAGE_KEY = "agenhood.apiLog";

let entries: ApiLogEntry[] = load();
// Resume the id counter past any entries restored from sessionStorage so a
// post-reload logStart can't collide with (and overwrite) a restored entry.
let seq = entries.reduce((m, e) => Math.max(m, Number(e.id) || 0), 0);
const listeners = new Set<() => void>();

function load(): ApiLogEntry[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as ApiLogEntry[]) : [];
    return Array.isArray(parsed) ? parsed.slice(0, CAPACITY) : [];
  } catch {
    return [];
  }
}

function persist(): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    /* storage full / unavailable — keep going, logging must never throw */
  }
}

function notify(): void {
  for (const l of listeners) l();
}

function emit(): void {
  persist();
  notify();
}

export function getEntries(): ApiLogEntry[] {
  return entries;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

type StartInput = Pick<ApiLogEntry, "kind" | "method" | "path"> &
  Partial<Pick<ApiLogEntry, "requestBody" | "sessionOnly" | "sse">>;

export function logStart(input: StartInput): string {
  const id = `${++seq}`;
  const entry: ApiLogEntry = { id, startedAt: Date.now(), ...input };
  entries = [entry, ...entries].slice(0, CAPACITY);
  emit();
  return id;
}

// Merge a patch without finalizing timing (used for in-flight SSE updates).
export function logUpdate(id: string, patch: Partial<ApiLogEntry>): void {
  entries = entries.map((e) => (e.id === id ? { ...e, ...patch } : e));
  notify();
}

// Merge a patch and stamp durationMs from startedAt.
export function logEnd(id: string, patch: Partial<ApiLogEntry>): void {
  entries = entries.map((e) =>
    e.id === id ? { ...e, ...patch, durationMs: Date.now() - e.startedAt } : e,
  );
  emit();
}

export function clearLog(): void {
  entries = [];
  emit();
}

// React binding. getEntries returns a stable reference between changes,
// so useSyncExternalStore re-renders only when the buffer actually changes.
export function useApiLog(): ApiLogEntry[] {
  return useSyncExternalStore(subscribe, getEntries, getEntries);
}

// Count-only binding so the header button re-renders on count change
// without subscribing to full entry payloads.
export function useApiLogCount(): number {
  return useSyncExternalStore(
    subscribe,
    () => entries.length,
    () => entries.length,
  );
}
