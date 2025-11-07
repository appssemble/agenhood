import { describe, it, expect, beforeEach } from "vitest";
import { logStart, logUpdate, logEnd, getEntries, clearLog, subscribe, CAPACITY } from "./store";

beforeEach(() => clearLog());

describe("apiLog store", () => {
  it("adds entries newest-first and settles them", () => {
    const id = logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    logEnd(id, { status: 200, ok: true });
    const [e] = getEntries();
    expect(e.method).toBe("GET");
    expect(e.status).toBe(200);
    expect(e.ok).toBe(true);
    expect(typeof e.durationMs).toBe("number");
  });

  it("logUpdate merges without setting duration", () => {
    const id = logStart({ kind: "sse", method: "SSE", path: "/v1/c/t/events", sse: { events: 0, closed: false } });
    logUpdate(id, { sse: { events: 2, closed: false } });
    const [e] = getEntries();
    expect(e.sse).toEqual({ events: 2, closed: false });
    expect(e.durationMs).toBeUndefined();
  });

  it("caps the buffer at CAPACITY, evicting oldest", () => {
    for (let i = 0; i < CAPACITY + 10; i++) logStart({ kind: "rest", method: "GET", path: `/v1/x/${i}` });
    const entries = getEntries();
    expect(entries.length).toBe(CAPACITY);
    expect(entries[0].path).toBe(`/v1/x/${CAPACITY + 9}`); // newest first
  });

  it("notifies subscribers on change", () => {
    let calls = 0;
    const unsub = subscribe(() => { calls++; });
    logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    expect(calls).toBe(1);
    unsub();
    logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    expect(calls).toBe(1);
  });

  it("clearLog empties the buffer", () => {
    logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    clearLog();
    expect(getEntries()).toEqual([]);
  });

  it("keeps ids unique across a simulated reload", () => {
    const a = logStart({ kind: "rest", method: "GET", path: "/v1/a" });
    const b = logStart({ kind: "rest", method: "GET", path: "/v1/b" });
    expect(a).not.toBe(b);
    expect(Number(b)).toBeGreaterThan(Number(a));
  });
});
