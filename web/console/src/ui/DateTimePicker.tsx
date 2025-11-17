import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icons } from "./Icon";

/**
 * Date + time picker with a calendar popover (portaled, fixed-position, flips
 * up near the viewport edge) plus a time field. Value/onChange use the native
 * datetime-local string format "YYYY-MM-DDTHH:mm" so it drops into existing
 * forms unchanged. Past days are disabled by default (future-run friendly).
 */

const WEEK = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

type Parsed = { y: number; mo: number; d: number; time: string };

function parse(v: string): Parsed | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  if (!m) return null;
  return { y: +m[1], mo: +m[2] - 1, d: +m[3], time: `${m[4]}:${m[5]}` };
}

function midnight(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

export function DateTimePicker({
  value,
  onChange,
  id,
  disablePast = true,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  id?: string;
  disablePast?: boolean;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const trigRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const parsed = parse(value);
  const today = midnight(new Date());
  const time = parsed?.time ?? "09:00";

  const [view, setView] = useState(() =>
    parsed ? { y: parsed.y, mo: parsed.mo } : { y: today.getFullYear(), mo: today.getMonth() },
  );

  // Re-centre the calendar on the selected month whenever the popover opens.
  useEffect(() => {
    if (open && parsed) setView({ y: parsed.y, mo: parsed.mo });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close on outside click (popover is portaled, so check it explicitly).
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Anchor the fixed-position popover to the trigger; flip up if needed.
  const [pos, setPos] = useState<React.CSSProperties>({});
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigRef.current;
      if (!t) return;
      const r = t.getBoundingClientRect();
      const gap = 6;
      const popH = 360;
      const below = window.innerHeight - r.bottom;
      const up = below < popH && r.top > below;
      setPos({
        position: "fixed",
        left: Math.round(r.left),
        zIndex: 1000,
        ...(up
          ? { bottom: Math.round(window.innerHeight - r.top + gap) }
          : { top: Math.round(r.bottom + gap) }),
      });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  function emit(d: Date, t: string) {
    onChange(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${t}`);
  }

  function pickDay(d: Date) {
    if (d.getMonth() !== view.mo) setView({ y: d.getFullYear(), mo: d.getMonth() });
    emit(d, time);
  }

  function changeTime(t: string) {
    if (!t) return;
    const base = parsed ? new Date(parsed.y, parsed.mo, parsed.d) : today;
    emit(base, t);
  }

  // 6×7 grid starting on the Monday of the first visible week.
  const first = new Date(view.y, view.mo, 1);
  const startOffset = (first.getDay() + 6) % 7; // Monday-first
  const gridStart = new Date(view.y, view.mo, 1 - startOffset);
  const cells = Array.from({ length: 42 }, (_, i) =>
    new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i),
  );

  const monthLabel = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const triggerLabel = parsed
    ? new Date(parsed.y, parsed.mo, parsed.d).toLocaleDateString(undefined, {
        weekday: "short", month: "short", day: "numeric", year: "numeric",
      }) + " · " + parsed.time
    : null;

  const popover = (
    <div ref={popRef} className="dtp-pop" style={pos} role="dialog" aria-label="Choose date and time">
      <div className="dtp-head">
        <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label="Previous month"
          onClick={() => setView((v) => (v.mo === 0 ? { y: v.y - 1, mo: 11 } : { y: v.y, mo: v.mo - 1 }))}>
          <Icons.ArrowLeft w={15} />
        </button>
        <span className="dtp-title">{monthLabel}</span>
        <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label="Next month"
          onClick={() => setView((v) => (v.mo === 11 ? { y: v.y + 1, mo: 0 } : { y: v.y, mo: v.mo + 1 }))}>
          <Icons.ArrowRight w={15} />
        </button>
      </div>

      <div className="dtp-grid">
        {WEEK.map((w) => <div key={w} className="dtp-wd">{w}</div>)}
        {cells.map((d) => {
          const out = d.getMonth() !== view.mo;
          const disabled = disablePast && d.getTime() < today.getTime();
          const isToday = d.getTime() === today.getTime();
          const sel = !!parsed && d.getFullYear() === parsed.y && d.getMonth() === parsed.mo && d.getDate() === parsed.d;
          return (
            <button
              type="button"
              key={d.toISOString()}
              className={"dtp-day" + (out ? " out" : "") + (isToday ? " today" : "") + (sel ? " sel" : "")}
              disabled={disabled}
              aria-pressed={sel}
              aria-label={d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
              onClick={() => pickDay(d)}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>

      <div className="dtp-foot">
        <span className="dtp-foot-lab">Time</span>
        <input
          type="time"
          className="input"
          aria-label="Time"
          value={time}
          onChange={(e) => changeTime(e.target.value)}
          style={{ width: 130 }}
        />
        <button type="button" className="btn btn-primary btn-sm" style={{ marginLeft: "auto" }} onClick={() => setOpen(false)}>
          Done
        </button>
      </div>
    </div>
  );

  return (
    <div className="dtp" ref={rootRef}>
      <button
        type="button"
        id={id}
        ref={trigRef}
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={"select dd-trigger dtp-trigger" + (open ? " open" : "")}
        onClick={() => setOpen((o) => !o)}
      >
        <Icons.Calendar w={15} style={{ flex: "0 0 auto", color: "var(--muted)" }} />
        <span className={triggerLabel ? undefined : "dd-placeholder"}>
          {triggerLabel ?? "Select date & time"}
        </span>
      </button>
      {open && createPortal(popover, document.body)}
    </div>
  );
}
