import { describe, it, expect } from "vitest";
import { stepDurations } from "./timing";

const T = (s: string) => `2026-09-02T10:00:${s}+00:00`;

describe("stepDurations", () => {
  it("measures each entry against the next one", () => {
    const out = stepDurations([T("00"), T("02"), T("05")], Date.parse(T("09")));
    expect(out).toEqual([2000, 3000, 4000]);
  });

  it("measures the last entry against endMs", () => {
    const out = stepDurations([T("00")], Date.parse(T("07")));
    expect(out).toEqual([7000]);
  });

  it("skips entries with no timestamp when looking for the next one", () => {
    // The synthetic `result` row has no ts, so the real last step must still
    // run all the way to the end of the task rather than stopping at it.
    const out = stepDurations([T("00"), undefined], Date.parse(T("06")));
    expect(out).toEqual([6000, null]);
  });

  it("gives no duration to an entry whose own timestamp is unparseable", () => {
    const out = stepDurations([T("00"), "nonsense", T("04")], Date.parse(T("04")));
    expect(out).toEqual([4000, null, 0]);
  });

  it("clamps a negative gap to zero (container/control-plane clock skew)", () => {
    const out = stepDurations([T("05")], Date.parse(T("00")));
    expect(out).toEqual([0]);
  });

  it("gives the last entry no duration when endMs is not a number", () => {
    const out = stepDurations([T("00")], NaN);
    expect(out).toEqual([null]);
  });

  it("returns an empty list for no entries", () => {
    expect(stepDurations([], Date.now())).toEqual([]);
  });
});
