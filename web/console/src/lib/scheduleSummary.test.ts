import { describe, it, expect } from "vitest";
import { scheduleSummary, scheduleParts } from "./scheduleSummary";

describe("scheduleParts", () => {
  it("one-time: chip only, not recurring", () => {
    expect(scheduleParts({ kind: "once" }, "UTC")).toEqual({ cadence: "One-time", recurring: false, detail: "" });
  });
  it("daily: cadence + time · tz", () => {
    expect(scheduleParts({ kind: "recurring", unit: "day", time: "09:00" }, "UTC")).toEqual({
      cadence: "Daily", recurring: true, detail: "09:00 · UTC",
    });
  });
  it("weekly: cadence + days · time · tz", () => {
    expect(scheduleParts({ kind: "recurring", unit: "week", time: "08:00", weekdays: [1, 2] }, "UTC")).toEqual({
      cadence: "Weekly", recurring: true, detail: "Mon, Tue · 08:00 · UTC",
    });
  });
  it("monthly: cadence + day-of-month · time · tz", () => {
    expect(scheduleParts({ kind: "recurring", unit: "month", time: "09:00", day_of_month: 15 }, "UTC")).toEqual({
      cadence: "Monthly", recurring: true, detail: "Day 15 · 09:00 · UTC",
    });
  });
  it("hourly: cadence + 'every hour'", () => {
    expect(scheduleParts({ kind: "recurring", unit: "hour" }, "UTC")).toEqual({
      cadence: "Hourly", recurring: true, detail: "every hour",
    });
  });
});

describe("scheduleSummary", () => {
  it("describes a one-time schedule", () => {
    expect(scheduleSummary({ kind: "once" }, "UTC", "2026-06-17T09:00:00+00:00")).toMatch(/Once/);
  });
  it("describes hourly", () => {
    expect(scheduleSummary({ kind: "recurring", unit: "hour" }, "UTC", null)).toBe("Every hour (UTC)");
  });
  it("describes daily", () => {
    expect(scheduleSummary({ kind: "recurring", unit: "day", time: "09:00" }, "UTC", null)).toBe("Daily at 09:00 (UTC)");
  });
  it("describes weekly with weekdays", () => {
    const s = scheduleSummary({ kind: "recurring", unit: "week", time: "09:00", weekdays: [1, 5] }, "UTC", null);
    expect(s).toBe("Weekly on Mon, Fri at 09:00 (UTC)");
  });
  it("describes monthly", () => {
    expect(scheduleSummary({ kind: "recurring", unit: "month", time: "09:00", day_of_month: 15 }, "UTC", null)).toBe("Monthly on day 15 at 09:00 (UTC)");
  });
});
