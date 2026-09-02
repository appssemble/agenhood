import { useEffect, useState } from "react";

/** `Date.now()`, refreshed once a second while `enabled`.
 *
 *  Lets a running task's elapsed time advance on screen without every view
 *  that needs it running an interval of its own. Disabled — a settled task —
 *  it returns a frozen value and schedules nothing. */
export function useNowTick(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [enabled]);
  return now;
}
