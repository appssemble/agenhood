import type { ScheduleSpec } from "../api/types";

const DAYS = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Human-readable one-line summary of a schedule. `runAt` is the ISO next_run_at
 *  used for one-time schedules. */
export function scheduleSummary(s: ScheduleSpec, timezone: string, runAt: string | null): string {
  if (s.kind === "once") {
    if (runAt) {
      const d = new Date(runAt);
      return `Once on ${d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
    }
    return "Once";
  }
  const tz = ` (${timezone})`;
  switch (s.unit) {
    case "hour":
      return `Every hour${tz}`;
    case "day":
      return `Daily at ${s.time}${tz}`;
    case "week": {
      const days = (s.weekdays ?? []).slice().sort((a, b) => a - b).map((d) => DAYS[d]).join(", ");
      return `Weekly on ${days} at ${s.time}${tz}`;
    }
    case "month":
      return `Monthly on day ${s.day_of_month} at ${s.time}${tz}`;
    default:
      return `Recurring${tz}`;
  }
}

export interface ScheduleParts {
  /** The cadence at a glance: "Daily" | "Weekly" | "Monthly" | "Hourly" | "One-time" | "Recurring". */
  cadence: string;
  /** Whether the schedule repeats (false for one-time). Drives the chip colour. */
  recurring: boolean;
  /** Concise specifics (time, days, day-of-month, timezone); empty when the cadence says it all. */
  detail: string;
}

/** Structured form of a schedule for a scannable two-part display: a cadence
 *  chip + concise detail. Complements `scheduleSummary` (used on detail pages). */
export function scheduleParts(s: ScheduleSpec, timezone: string): ScheduleParts {
  if (s.kind === "once") {
    return { cadence: "One-time", recurring: false, detail: "" };
  }
  switch (s.unit) {
    case "hour":
      return { cadence: "Hourly", recurring: true, detail: "every hour" };
    case "day":
      return { cadence: "Daily", recurring: true, detail: `${s.time} · ${timezone}` };
    case "week": {
      const days = (s.weekdays ?? []).slice().sort((a, b) => a - b).map((d) => DAYS[d]).join(", ");
      return { cadence: "Weekly", recurring: true, detail: `${days} · ${s.time} · ${timezone}` };
    }
    case "month":
      return { cadence: "Monthly", recurring: true, detail: `Day ${s.day_of_month} · ${s.time} · ${timezone}` };
    default:
      return { cadence: "Recurring", recurring: true, detail: timezone };
  }
}
