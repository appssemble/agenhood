import { describe, it, expect, vi, beforeEach } from "vitest";
import { subscribeEvents } from "./events";
import type { Event } from "./types";
import { getEntries, clearLog } from "../apiLog/store";

// Minimal fake EventSource installed on globalThis.
class FakeEventSource {
  static last: FakeEventSource | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeEventSource.last = this; }
  emit(ev: Event) { this.onmessage?.({ data: JSON.stringify(ev) }); }
  fail() { this.onerror?.({}); }
  close() { this.closed = true; }
}

beforeEach(() => { (globalThis as any).EventSource = FakeEventSource; FakeEventSource.last = null; clearLog(); });

describe("subscribeEvents", () => {
  it("delivers parsed events in order", () => {
    const got: Event[] = [];
    subscribeEvents("con_1", "tsk_1", { onEvent: (e) => got.push(e), onError: () => {} });
    const src = FakeEventSource.last!;
    src.emit({ seq: 1, type: "task_started", ts: "t", payload: { driver: "vanilla", model: "m" } });
    src.emit({ seq: 2, type: "assistant_message", ts: "t", payload: { content: [] } });
    expect(got.map((e) => e.seq)).toEqual([1, 2]);
  });

  it("opens at the base URL initially and resumes with after_seq", () => {
    subscribeEvents("con_1", "tsk_1", { onEvent: () => {}, onError: () => {}, afterSeq: 5 });
    expect(FakeEventSource.last!.url).toContain("/v1/containers/con_1/tasks/tsk_1/events?after_seq=5");
  });

  it("returns an unsubscribe that closes the source", () => {
    const stop = subscribeEvents("con_1", "tsk_1", { onEvent: () => {}, onError: () => {} });
    const src = FakeEventSource.last!;
    stop();
    expect(src.closed).toBe(true);
  });

  it("invokes onError when the stream errors", () => {
    const onError = vi.fn();
    subscribeEvents("con_1", "tsk_1", { onEvent: () => {}, onError });
    FakeEventSource.last!.fail();
    expect(onError).toHaveBeenCalledOnce();
  });

  it("logs the stream lifecycle into the apiLog store", () => {
    const stop = subscribeEvents("con_1", "tsk_1", { onEvent: () => {}, onError: () => {} });
    const src = FakeEventSource.last!;
    src.emit({ seq: 1, type: "task_started", ts: "t", payload: { driver: "vanilla", model: "m" } });
    let [e] = getEntries();
    expect(e.kind).toBe("sse");
    expect(e.method).toBe("SSE");
    expect(e.path).toBe("/v1/containers/con_1/tasks/tsk_1/events");
    expect(e.sse).toEqual({ events: 1, closed: false });
    stop();
    [e] = getEntries();
    expect(e.sse).toEqual({ events: 1, closed: true });
    expect(typeof e.durationMs).toBe("number");
  });
});
