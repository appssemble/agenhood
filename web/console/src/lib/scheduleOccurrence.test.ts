import { describe, it, expect } from "vitest";
import { occursOn, occurrenceTime, buildMonthGrid, isoWeekday, isSameDay } from "./scheduleOccurrence";
import type { ScheduleSpec } from "../api/types";

const d = (y: number, m: number, day: number) => new Date(y, m - 1, day);

describe("occursOn", () => {
  it("daily and hourly run every day", () => {
    expect(occursOn({ kind: "recurring", unit: "day", time: "09:00" }, d(2026, 6, 10), null)).toBe(true);
    expect(occursOn({ kind: "recurring", unit: "hour" }, d(2026, 6, 10), null)).toBe(true);
  });
  it("weekly matches its ISO weekdays only", () => {
    const day = d(2026, 6, 10);
    expect(occursOn({ kind: "recurring", unit: "week", time: "08:00", weekdays: [isoWeekday(day)] }, day, null)).toBe(true);
    const other = isoWeekday(day) === 1 ? 2 : 1;
    expect(occursOn({ kind: "recurring", unit: "week", time: "08:00", weekdays: [other] }, day, null)).toBe(false);
  });
  it("monthly matches its day_of_month only", () => {
    expect(occursOn({ kind: "recurring", unit: "month", time: "09:00", day_of_month: 15 }, d(2026, 6, 15), null)).toBe(true);
    expect(occursOn({ kind: "recurring", unit: "month", time: "09:00", day_of_month: 15 }, d(2026, 6, 16), null)).toBe(false);
  });
  it("one-time matches its nextRunAt date, false without one", () => {
    const spec: ScheduleSpec = { kind: "once" };
    expect(occursOn(spec, d(2026, 6, 20), "2026-06-20T14:00:00")).toBe(true);
    expect(occursOn(spec, d(2026, 6, 21), "2026-06-20T14:00:00")).toBe(false);
    expect(occursOn(spec, d(2026, 6, 20), null)).toBe(false);
  });
});

describe("occurrenceTime", () => {
  it("returns the recurring time / 'hourly'", () => {
    expect(occurrenceTime({ kind: "recurring", unit: "day", time: "09:00" }, null)).toBe("09:00");
    expect(occurrenceTime({ kind: "recurring", unit: "hour" }, null)).toBe("hourly");
  });
  it("formats a one-time local HH:MM", () => {
    expect(occurrenceTime({ kind: "once" }, "2026-06-20T14:05:00")).toBe("14:05");
    expect(occurrenceTime({ kind: "once" }, null)).toBe("");
  });
});

describe("buildMonthGrid", () => {
  it("returns 42 dates starting on a Monday and covering the month", () => {
    const g = buildMonthGrid(2026, 5); // June (month index 5)
    expect(g).toHaveLength(42);
    expect(isoWeekday(g[0])).toBe(1); // Monday
    expect(g.some((x) => isSameDay(x, new Date(2026, 5, 1)))).toBe(true);
    expect(g.some((x) => isSameDay(x, new Date(2026, 5, 30)))).toBe(true);
  });
});
