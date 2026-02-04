import { useMemo, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  useCreateScheduledTask, useUpdateScheduledTask, useScheduledTask,
  useContainers, usePrompts, useWorkflows,
} from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../components/Toast";
import { scheduleSummary } from "../lib/scheduleSummary";
import { Button, SegControl, Note } from "../ui";
import { Field } from "../ui/Field";
import { Input } from "../ui/inputs";
import { Dropdown } from "../ui/Dropdown";
import { DateTimePicker } from "../ui/DateTimePicker";
import { Icons } from "../ui/Icon";
import type { ScheduleSpec, ScheduleUnit, ScheduledTask, ScheduleTarget } from "../api/types";

const WEEKDAYS = [
  { n: 1, label: "Mon" }, { n: 2, label: "Tue" }, { n: 3, label: "Wed" },
  { n: 4, label: "Thu" }, { n: 5, label: "Fri" }, { n: 6, label: "Sat" }, { n: 7, label: "Sun" },
];
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTE_STEPS = ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"];

const TZ_LIST: string[] = (() => {
  try {
    const fn = (Intl as { supportedValuesOf?: (key: "timeZone") => string[] }).supportedValuesOf;
    const zones = fn ? fn.call(Intl, "timeZone") : [];
    if (zones.length) return zones;
  } catch { /* fall through to curated list */ }
  return [
    "UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Bucharest",
    "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney",
  ];
})();

function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function ScheduledTaskFormInner({
  existing,
  prefillKind,
  prefillPromptId,
  prefillWorkflowId,
}: {
  existing: ScheduledTask | null;
  prefillKind?: "prompt" | "workflow";
  prefillPromptId?: string;
  prefillWorkflowId?: string;
}) {
  const { sid } = useParams<{ sid?: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const editing = existing !== null;

  const create = useCreateScheduledTask();
  const update = useUpdateScheduledTask(sid ?? "");

  const containersQ = useContainers();
  const promptsQ = usePrompts();
  const workflowsQ = useWorkflows();

  const containers = containersQ.data?.containers ?? [];
  const prompts = promptsQ.data?.prompts ?? [];
  const workflows = workflowsQ.data?.workflows ?? [];

  // --- Target kind ---
  const initialKind: "prompt" | "workflow" = (() => {
    if (existing?.target.kind) return existing.target.kind;
    if (prefillKind) return prefillKind;
    return "prompt";
  })();
  const [targetKind, setTargetKind] = useState<"prompt" | "workflow">(initialKind);

  // --- Prompt target fields ---
  const initialPromptId = existing?.target.kind === "prompt"
    ? existing.target.prompt_id
    : (prefillPromptId ?? "");
  const initialContainerId = existing?.target.kind === "prompt"
    ? existing.target.container_id
    : "";
  const initialVariables = existing?.target.kind === "prompt"
    ? existing.target.variables
    : {};

  const [promptId, setPromptId] = useState(initialPromptId);
  const [containerId, setContainerId] = useState(initialContainerId);
  const [variables, setVariables] = useState<Record<string, string>>(initialVariables);

  const selectedPrompt = prompts.find((p) => p.id === promptId);

  function handlePromptChange(newId: string) {
    setPromptId(newId);
    const p = prompts.find((x) => x.id === newId);
    const newVars: Record<string, string> = {};
    if (p) {
      for (const v of p.variables) {
        // Preserve existing values if the variable exists
        newVars[v.name] = variables[v.name] ?? "";
      }
    }
    setVariables(newVars);
  }

  function handleVariableChange(name: string, value: string) {
    setVariables((v) => ({ ...v, [name]: value }));
  }

  // --- Workflow target fields ---
  const initialWorkflowId = existing?.target.kind === "workflow"
    ? existing.target.workflow_id
    : (prefillWorkflowId ?? "");
  const [workflowId, setWorkflowId] = useState(initialWorkflowId);

  // --- Common fields ---
  const [name, setName] = useState(existing?.name ?? "");

  // --- Schedule fields ---
  const [timezone, setTimezone] = useState(existing?.timezone ?? BROWSER_TZ);
  const [schedKind, setSchedKind] = useState<"once" | "recurring">(existing?.schedule.kind ?? "recurring");
  const [unit, setUnit] = useState<ScheduleUnit>(existing?.schedule.unit ?? "day");
  const [time, setTime] = useState(existing?.schedule.time ?? "09:00");
  const [weekdays, setWeekdays] = useState<number[]>(existing?.schedule.weekdays ?? [1]);
  const [dayOfMonth, setDayOfMonth] = useState(existing?.schedule.day_of_month ?? 1);
  const [runAt, setRunAt] = useState<string>(
    existing?.schedule.kind === "once" ? isoToLocalInput(existing.next_run_at) : ""
  );

  const summaryText = useMemo(() => {
    if (schedKind === "once") {
      if (!runAt) return "Pick a date and time for this run.";
      const d = new Date(runAt);
      const iso = Number.isNaN(d.getTime()) ? null : d.toISOString();
      return scheduleSummary({ kind: "once" }, timezone, iso);
    }
    const spec: ScheduleSpec =
      unit === "hour" ? { kind: "recurring", unit: "hour" }
        : unit === "week" ? { kind: "recurring", unit: "week", time, weekdays }
          : unit === "month" ? { kind: "recurring", unit: "month", time, day_of_month: dayOfMonth }
            : { kind: "recurring", unit: "day", time };
    return scheduleSummary(spec, timezone, null);
  }, [schedKind, runAt, unit, time, weekdays, dayOfMonth, timezone]);

  const tzOptions = useMemo(() => {
    const set = new Set(TZ_LIST);
    set.add(BROWSER_TZ);
    if (timezone) set.add(timezone);
    return Array.from(set).sort();
  }, [timezone]);

  const [hh, mm] = (() => {
    const [h, m] = time.split(":");
    return [(h ?? "09").padStart(2, "0"), (m ?? "00").padStart(2, "0")];
  })();
  const minuteOptions = MINUTE_STEPS.includes(mm) ? MINUTE_STEPS : [...MINUTE_STEPS, mm].sort();

  function buildSchedule(): ScheduleSpec {
    if (schedKind === "once") return { kind: "once" };
    if (unit === "hour") return { kind: "recurring", unit: "hour" };
    if (unit === "week") return { kind: "recurring", unit: "week", time, weekdays };
    if (unit === "month") return { kind: "recurring", unit: "month", time, day_of_month: dayOfMonth };
    return { kind: "recurring", unit: "day", time };
  }

  function toggleWeekday(n: number) {
    setWeekdays((w) => {
      if (w.includes(n)) {
        if (w.length === 1) return w;
        return w.filter((d) => d !== n);
      }
      return [...w, n];
    });
  }

  function buildTarget(): ScheduleTarget {
    if (targetKind === "workflow") {
      return { kind: "workflow", workflow_id: workflowId };
    }
    return { kind: "prompt", container_id: containerId, prompt_id: promptId, variables };
  }

  const targetValid = targetKind === "workflow"
    ? !!workflowId
    : !!promptId && !!containerId;

  const canSave =
    !!name &&
    targetValid &&
    !(schedKind === "once" && !runAt) &&
    !create.isPending &&
    !update.isPending;

  async function onSubmit() {
    const schedule = buildSchedule();
    const target = buildTarget();
    try {
      const run_at = schedKind === "once" ? new Date(runAt).toISOString() : null;
      if (editing) {
        await update.mutateAsync({ name, target, schedule, timezone, run_at });
      } else {
        await create.mutateAsync({ name, target, schedule, timezone, run_at });
      }
      navigate("/schedules");
    } catch (err) {
      toast.error("Couldn't save scheduled run", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="page">
      <button
        className="btn btn-ghost btn-sm"
        onClick={() => navigate("/schedules")}
        style={{ gap: 6, padding: "4px 8px 4px 4px", marginBottom: 8, marginLeft: -4 }}
      >
        <Icons.ArrowLeft w={15} /> Scheduled runs
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 18 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {editing ? "Edit scheduled run" : "New scheduled run"}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>
            Run a prompt or workflow automatically on a schedule.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <Button variant="secondary" size="sm" onClick={() => navigate("/schedules")}>Cancel</Button>
          <Button variant="primary" size="sm" style={{ gap: 6 }} onClick={onSubmit} disabled={!canSave}>
            <Icons.Clock w={14} /> {editing ? "Save scheduled run" : "Create scheduled run"}
          </Button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 760 }}>
        {/* 1 — Trigger */}
        <section className="section-card">
          <div className="section-card-head">
            <span className="nc-step">1</span>
            <div className="section-card-titles">
              <span className="section-card-title">Trigger</span>
              <span className="section-card-hint">What runs each time this fires.</span>
            </div>
          </div>
          <div className="section-card-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Name" htmlFor="st-name">
              <Input id="st-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Nightly report" />
            </Field>

            <div className="field" style={{ alignItems: "flex-start" }}>
              <label>Target</label>
              <SegControl<"prompt" | "workflow">
                value={targetKind}
                onChange={setTargetKind}
                options={[
                  { value: "prompt", label: "Prompt" },
                  { value: "workflow", label: "Workflow" },
                ]}
              />
            </div>

            {targetKind === "prompt" ? (
              <>
                <div className="wfb-grid2">
                  <Field label="Prompt" htmlFor="st-prompt-sel">
                    <Dropdown
                      id="st-prompt-sel"
                      aria-label="Prompt"
                      portal
                      placeholder="Select prompt…"
                      value={promptId}
                      onChange={handlePromptChange}
                      options={prompts.map((p) => ({ value: p.id, label: p.name }))}
                    />
                  </Field>
                  <Field label="Runs on" htmlFor="st-container-sel">
                    <Dropdown
                      id="st-container-sel"
                      aria-label="Container"
                      portal
                      placeholder="Select container…"
                      value={containerId}
                      onChange={setContainerId}
                      options={containers.map((c) => ({ value: c.id, label: c.name }))}
                    />
                  </Field>
                </div>

                {selectedPrompt && selectedPrompt.variables.length > 0 && (
                  <div className="wfb-vars">
                    <div className="wfb-vars-lab">Variables</div>
                    <div className="wfb-vars-grid">
                      {selectedPrompt.variables.map((v) => (
                        <div key={v.name}>
                          <label className="wfb-var-lab" htmlFor={`st-var-${v.name}`}>{`{{${v.name}}}`}</label>
                          <input
                            id={`st-var-${v.name}`}
                            aria-label={`Variable ${v.name}`}
                            className="input"
                            value={variables[v.name] ?? ""}
                            onChange={(e) => handleVariableChange(v.name, e.target.value)}
                            placeholder={v.default || "value"}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <Field label="Workflow" htmlFor="st-workflow-sel">
                <Dropdown
                  id="st-workflow-sel"
                  aria-label="Workflow"
                  portal
                  placeholder="Select workflow…"
                  value={workflowId}
                  onChange={setWorkflowId}
                  options={workflows.map((w) => ({ value: w.id, label: w.name }))}
                />
              </Field>
            )}
          </div>
        </section>

        {/* 2 — Schedule */}
        <section className="section-card">
          <div className="section-card-head">
            <span className="nc-step">2</span>
            <div className="section-card-titles">
              <span className="section-card-title">Schedule</span>
              <span className="section-card-hint">When this runs.</span>
            </div>
          </div>
          <div className="section-card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
              <label>Frequency</label>
              <SegControl<"once" | "recurring">
                value={schedKind}
                onChange={setSchedKind}
                options={[
                  { value: "recurring", label: "Recurring" },
                  { value: "once", label: "Run once" },
                ]}
              />
            </div>

            {schedKind === "once" ? (
              <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
                <label htmlFor="st-runat">Run at</label>
                <DateTimePicker id="st-runat" aria-label="Run at" value={runAt} onChange={setRunAt} />
              </div>
            ) : (
              <>
                <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
                  <label>Repeat</label>
                  <SegControl<ScheduleUnit>
                    value={unit}
                    onChange={setUnit}
                    options={[
                      { value: "hour", label: "Hourly" },
                      { value: "day", label: "Daily" },
                      { value: "week", label: "Weekly" },
                      { value: "month", label: "Monthly" },
                    ]}
                  />
                </div>

                {unit === "week" && (
                  <div className="field" style={{ margin: 0 }}>
                    <label>On these days</label>
                    <div role="group" aria-label="Days of week" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {WEEKDAYS.map((d) => {
                        const on = weekdays.includes(d.n);
                        return (
                          <button
                            type="button"
                            key={d.n}
                            aria-pressed={on}
                            onClick={() => toggleWeekday(d.n)}
                            style={{
                              flex: "1 1 0",
                              minWidth: 38,
                              padding: "8px 0",
                              fontFamily: "var(--font-ui)",
                              fontSize: 12,
                              fontWeight: 600,
                              cursor: "pointer",
                              borderRadius: 8,
                              border: `1px solid ${on ? "var(--ink)" : "var(--border)"}`,
                              background: on ? "var(--ink)" : "var(--surface-3)",
                              color: on ? "var(--surface)" : "var(--ink-2)",
                              transition: "background 150ms ease, border-color 150ms ease, color 150ms ease",
                            }}
                          >
                            {d.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {unit !== "hour" && (
                  <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
                    <label htmlFor="st-hour">Time</label>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Dropdown
                        id="st-hour"
                        aria-label="Hour"
                        portal
                        value={hh}
                        onChange={(v) => setTime(`${v}:${mm}`)}
                        width={78}
                        searchable={false}
                        options={HOURS.map((h) => ({ value: h, label: h }))}
                      />
                      <span style={{ color: "var(--muted)", fontWeight: 700 }}>:</span>
                      <Dropdown
                        aria-label="Minute"
                        portal
                        value={mm}
                        onChange={(v) => setTime(`${hh}:${v}`)}
                        width={78}
                        searchable={false}
                        options={minuteOptions.map((m) => ({ value: m, label: m }))}
                      />
                    </div>
                  </div>
                )}

                {unit === "month" && (
                  <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
                    <label htmlFor="st-dom">Day of month</label>
                    <Input id="st-dom" type="number" min={1} max={31} value={dayOfMonth} onChange={(e) => setDayOfMonth(Number(e.target.value))} style={{ width: 100 }} />
                    <span className="hint">Shorter months use their last day.</span>
                  </div>
                )}

                <div className="field" style={{ margin: 0, alignItems: "flex-start" }}>
                  <label htmlFor="st-tz">Timezone</label>
                  <Dropdown
                    id="st-tz"
                    aria-label="Timezone"
                    portal
                    value={timezone}
                    onChange={setTimezone}
                    searchable
                    width={320}
                    options={tzOptions.map((tz) => ({ value: tz, label: tz }))}
                  />
                  <span className="hint">The time above is interpreted in this timezone.</span>
                </div>
              </>
            )}

            <Note style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
              <Icons.Clock w={14} style={{ flex: "0 0 auto", color: "var(--muted)" }} />
              <span>{summaryText}</span>
            </Note>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function ScheduledTaskForm() {
  const { sid } = useParams<{ sid?: string }>();
  const [searchParams] = useSearchParams();

  const prefillKind = searchParams.get("kind") as "prompt" | "workflow" | null ?? undefined;
  const prefillPromptId = searchParams.get("prompt_id") ?? undefined;
  const prefillWorkflowId = searchParams.get("workflow_id") ?? undefined;

  const existing = useScheduledTask(sid ?? "");

  if (!sid) {
    return (
      <ScheduledTaskFormInner
        existing={null}
        prefillKind={prefillKind}
        prefillPromptId={prefillPromptId}
        prefillWorkflowId={prefillWorkflowId}
      />
    );
  }
  if (existing.isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;
  if (existing.isError) return <div className="p-8 text-sm text-muted">Couldn't load this scheduled run.</div>;
  if (!existing.data) return <div className="p-8 text-sm text-muted">Loading…</div>;
  return <ScheduledTaskFormInner existing={existing.data} />;
}
