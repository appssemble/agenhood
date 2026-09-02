/** How long each entry in an ordered activity list took.
 *
 *  A step's duration is the gap to the *next* entry's start — we have no
 *  per-step measurement from most drivers, only the times at which events
 *  arrived. `endMs` closes out the final entry: the task's `ended_at` once
 *  settled, or a ticking `now` while it runs.
 *
 *  Entries with no usable timestamp are skipped when searching for the next
 *  start, so a trailing synthetic row (ChatTimeline's `result`) doesn't cut
 *  the last real step short. Negative gaps clamp to zero — event timestamps
 *  come from inside the container, `endMs` from the control plane, and the
 *  two clocks can disagree. */
export function stepDurations(
  starts: Array<string | null | undefined>,
  endMs: number,
): Array<number | null> {
  const ms = starts.map((s) => {
    const t = s == null ? NaN : Date.parse(s);
    return Number.isNaN(t) ? null : t;
  });
  return ms.map((start, i) => {
    if (start == null) return null;
    let next: number | null = null;
    for (let j = i + 1; j < ms.length; j++) {
      if (ms[j] != null) { next = ms[j]; break; }
    }
    if (next == null) next = Number.isFinite(endMs) ? endMs : null;
    if (next == null) return null;
    return Math.max(0, next - start);
  });
}
