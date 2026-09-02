import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useNowTick } from "./useNowTick";

afterEach(() => vi.useRealTimers());

describe("useNowTick", () => {
  it("advances about once a second while enabled", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-02T10:00:00Z"));
    const { result } = renderHook(() => useNowTick(true));
    const first = result.current;
    act(() => { vi.advanceTimersByTime(3000); });
    expect(result.current - first).toBeGreaterThanOrEqual(3000);
  });

  it("does not advance while disabled", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-02T10:00:00Z"));
    const { result } = renderHook(() => useNowTick(false));
    const first = result.current;
    act(() => { vi.advanceTimersByTime(5000); });
    expect(result.current).toBe(first);
  });

  it("stops ticking on unmount", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useNowTick(true));
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
