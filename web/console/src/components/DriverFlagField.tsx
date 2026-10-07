import { Field, SegControl, Switch } from "../ui";
import { REASONING_SUMMARY_DRIVERS } from "../api/types";

type Override = "" | "on" | "off";

const OVERRIDE_SEG: { value: Override; label: string }[] = [
  { value: "", label: "Default" },
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];

// Container/config surfaces: a plain on/off switch.
export function ReasoningSummarySwitch({
  driver, value, onChange,
}: {
  driver: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  if (!REASONING_SUMMARY_DRIVERS.includes(driver)) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Switch on={value} aria-label="Reasoning summaries" onClick={() => onChange(!value)} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--ink-2)" }}>Reasoning summaries</div>
        <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
          Emit short summaries of the model's thinking as task events
        </div>
      </div>
    </div>
  );
}

// Per-task surfaces: null inherits the container setting.
export function ReasoningSummaryOverride({
  driver, value, onChange,
}: {
  driver: string;
  value: boolean | null;
  onChange: (v: boolean | null) => void;
}) {
  if (!REASONING_SUMMARY_DRIVERS.includes(driver)) return null;
  const current: Override = value === null ? "" : value ? "on" : "off";
  return (
    <Field label="Reasoning summaries" hint="Show the model's thinking as events · Default inherits the container setting">
      <div role="group" aria-label="Reasoning summaries">
        <SegControl<Override>
          className="seg-fit"
          options={OVERRIDE_SEG}
          value={current}
          onChange={(v) => onChange(v === "" ? null : v === "on")}
        />
      </div>
    </Field>
  );
}
