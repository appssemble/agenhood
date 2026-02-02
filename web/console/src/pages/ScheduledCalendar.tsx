import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "../ui/Icon";
import { buildMonthGrid, occursOn, occurrenceTime, isSameDay } from "../lib/scheduleOccurrence";
import type { ScheduledTask, Prompt, Workflow } from "../api/types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function targetOf(s: ScheduledTask, prompts: Prompt[], workflows: Workflow[]): { kind: "workflow" | "prompt"; name: string } {
  if (s.target.kind === "workflow") {
    const wid = s.target.workflow_id;
    return { kind: "workflow", name: workflows.find((w) => w.id === wid)?.name ?? wid };
  }
  const pid = s.target.prompt_id;
  return { kind: "prompt", name: prompts.find((p) => p.id === pid)?.name ?? pid };
}

/** Month calendar of scheduled runs: recurring schedules expanded onto the days
 *  they fire (paused ones shown greyed). */
export function ScheduledCalendar({
  items, prompts, workflows,
}: {
  items: ScheduledTask[];
  prompts: Prompt[];
  workflows: Workflow[];
}) {
  const navigate = useNavigate();
  const today = new Date();
  const [{ y, m }, setView] = useState(() => ({ y: today.getFullYear(), m: today.getMonth() }));
  const grid = buildMonthGrid(y, m);

  function shift(delta: number) {
    setView((v) => {
      const d = new Date(v.y, v.m + delta, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });
  }

  return (
    <div className="card flush">
      <div className="cal-toolbar">
        <button type="button" className="cal-nav" aria-label="Previous month" onClick={() => shift(-1)}><Icons.ArrowLeft w={15} /></button>
        <div className="cal-month">{MONTHS[m]} {y}</div>
        <button type="button" className="cal-nav" aria-label="Next month" onClick={() => shift(1)}><Icons.ArrowRight w={15} /></button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setView({ y: today.getFullYear(), m: today.getMonth() })}>Today</button>
        <span className="spacer" />
        <span style={{ fontSize: 11, color: "var(--muted)", display: "inline-flex", alignItems: "center", gap: 12 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span className="cal-key cal-key-wf" /> Workflow</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span className="cal-key cal-key-pr" /> Prompt</span>
        </span>
      </div>

      <div className="cal-grid cal-head" aria-hidden>
        {WEEKDAYS.map((d) => <div key={d} className="cal-wkh">{d}</div>)}
      </div>

      <div className="cal-grid">
        {grid.map((date, i) => {
          const inMonth = date.getMonth() === m;
          const isToday = isSameDay(date, today);
          const runs = items
            .filter((s) => occursOn(s.schedule, date, s.next_run_at))
            .map((s) => ({ s, time: occurrenceTime(s.schedule, s.next_run_at), ...targetOf(s, prompts, workflows) }))
            .sort((a, b) => a.time.localeCompare(b.time));
          const shown = runs.slice(0, 3);
          return (
            <div key={i} className={`cal-cell ${inMonth ? "" : "out"} ${isToday ? "today" : ""}`.replace(/\s+/g, " ").trim()}>
              <span className="cal-num">{date.getDate()}</span>
              {shown.map(({ s, time, kind, name }) => (
                <button
                  key={s.id}
                  type="button"
                  className={`cal-chip ${kind === "workflow" ? "wf" : "pr"} ${s.enabled ? "" : "off"}`.replace(/\s+/g, " ").trim()}
                  title={`${name}${time ? ` · ${time}` : ""}${s.enabled ? "" : " · paused"}`}
                  onClick={() => navigate(`/schedules/${s.id}`)}
                >
                  {time && <span className="cal-chip-t">{time}</span>}
                  <span className="cal-chip-n">{name}</span>
                </button>
              ))}
              {runs.length > shown.length && <span className="cal-more">+{runs.length - shown.length} more</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
