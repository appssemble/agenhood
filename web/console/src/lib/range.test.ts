import { describe, it, expect } from "vitest";
import { rangeToParams, RANGES } from "./range";

const NOW = new Date("2026-06-03T12:00:00.000Z");

describe("rangeToParams", () => {
  it("24h → hour interval, 24h window", () => {
    const p = rangeToParams("24h", NOW);
    expect(p.interval).toBe("hour");
    expect(p.from).toBe("2026-06-02T12:00:00.000Z");
    expect(p.to).toBe("2026-06-03T12:00:00.000Z");
  });

  it("7d → day interval, 7-day window", () => {
    const p = rangeToParams("7d", NOW);
    expect(p.interval).toBe("day");
    expect(p.from).toBe("2026-05-27T12:00:00.000Z");
  });

  it("30d → day interval", () => {
    expect(rangeToParams("30d", NOW).interval).toBe("day");
  });

  it("exposes the selectable ranges", () => {
    expect(RANGES).toEqual(["24h", "7d", "30d"]);
  });
});
