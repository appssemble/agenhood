import type { ScheduleSpec } from "../api/types";

/** ISO weekday: 1 = Monday … 7 = Sunday. */
export function isoWeekday(d: Date): number {
  const g = d.getDay(); // 0 = Sun … 6 = Sat
  return g === 0 ? 7 : g;
}

export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Whether a schedule fires on the given calendar day. `nextRunAt` locates a
 *  one-time run (it has no recurrence rule). Recurring rules are evaluated from
 *  the spec regardless of enabled/paused — paused schedules are shown greyed. */
export function occursOn(spec: ScheduleSpec, date: Date, nextRunAt: string | null): boolean {
  if (spec.kind === "once") {
    if (!nextRunAt) return false;
    const t = Date.parse(nextRunAt);
    return !Number.isNaN(t) && isSameDay(new Date(t), date);
  }
  switch (spec.unit) {
    case "hour":
    case "day":
      return true;
    case "week":
      return (spec.weekdays ?? []).includes(isoWeekday(date));
    case "month":
      return date.getDate() === spec.day_of_month;
    default:
      return false;
  }
}

/** The time label for an occurrence chip: "HH:MM", "hourly", or "" if unknown. */
export function occurrenceTime(spec: ScheduleSpec, nextRunAt: string | null): string {
  if (spec.kind === "once") {
    if (!nextRunAt) return "";
    const d = new Date(nextRunAt);
    if (Number.isNaN(d.getTime())) return "";
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  if (spec.unit === "hour") return "hourly";
  return spec.time ?? "";
}

/** 42 dates (6 weeks, Monday-start) covering the given month, including the
 *  leading/trailing days from adjacent months. */
export function buildMonthGrid(year: number, month: number): Date[] {
  const lead = isoWeekday(new Date(year, month, 1)) - 1; // days before the 1st back to Monday
  const days: Date[] = [];
  for (let i = 0; i < 42; i++) days.push(new Date(year, month, 1 - lead + i));
  return days;
}
