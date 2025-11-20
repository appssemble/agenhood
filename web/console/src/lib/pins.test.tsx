import { renderHook, act } from "@testing-library/react";
import { usePins } from "./pins";

beforeEach(() => localStorage.clear());

test("toggles and persists pinned container ids", () => {
  const { result } = renderHook(() => usePins());
  expect(result.current.isPinned("ctr_1")).toBe(false);
  act(() => result.current.toggle("ctr_1"));
  expect(result.current.isPinned("ctr_1")).toBe(true);
  expect(JSON.parse(localStorage.getItem("ah.pins")!)).toContain("ctr_1");
});
