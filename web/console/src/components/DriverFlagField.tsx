import { Field, SegControl, Switch } from "../ui";
import { PROGRESS_UPDATES_DRIVERS, REASONING_SUMMARY_DRIVERS } from "../api/types";

// Boolean AgentConfig settings that only some drivers support.
export const DRIVER_FLAGS = {
  reasoning_summary: {
    label: "Reasoning summaries",
    description: "Emit short summaries of the model's thinking as task events",
    badge: "reasoning",
    drivers: REASONING_SUMMARY_DRIVERS,
  },
  progress_updates: {
    label: "Progress updates",
    description: "The agent describes each step in the user's language",
    badge: "progress",
    drivers: PROGRESS_UPDATES_DRIVERS,
  },
} as const;

export type DriverFlag = keyof typeof DRIVER_FLAGS;
export const DRIVER_FLAG_KEYS = Object.keys(DRIVER_FLAGS) as DriverFlag[];
// Per-task overrides: a missing key inherits the container setting.
export type FlagOverrides = Partial<Record<DriverFlag, boolean>>;

export function flagSupported(flag: DriverFlag, driver: string): boolean {
  return (DRIVER_FLAGS[flag].drivers as readonly string[]).includes(driver);
}

type Override = "" | "on" | "off";

const OVERRIDE_SEG: { value: Override; label: string }[] = [
  { value: "", label: "Default" },
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];

// Container/config surfaces: a plain on/off switch.
export function DriverFlagSwitch({
  flag, driver, value, onChange,
}: {
  flag: DriverFlag;
  driver: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  if (!flagSupported(flag, driver)) return null;
  const { label, description } = DRIVER_FLAGS[flag];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Switch on={value} aria-label={label} onClick={() => onChange(!value)} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--ink-2)" }}>{label}</div>
        <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{description}</div>
      </div>
    </div>
  );
}

// Per-task surfaces: undefined inherits the container setting.
export function DriverFlagOverride({
  flag, driver, value, onChange,
}: {
  flag: DriverFlag;
  driver: string;
  value: boolean | undefined;
  onChange: (v: boolean | undefined) => void;
}) {
  if (!flagSupported(flag, driver)) return null;
  const { label, description } = DRIVER_FLAGS[flag];
  const current: Override = value === undefined ? "" : value ? "on" : "off";
  return (
    <Field label={label} hint={`${description} · Default inherits the container setting`}>
      <div role="group" aria-label={label}>
        <SegControl<Override>
          className="seg-fit"
          options={OVERRIDE_SEG}
          value={current}
          onChange={(v) => onChange(v === "" ? undefined : v === "on")}
        />
      </div>
    </Field>
  );
}

// Every override control the driver supports, stacked.
export function DriverFlagOverrides({
  driver, value, onChange,
}: {
  driver: string;
  value: FlagOverrides;
  onChange: (v: FlagOverrides) => void;
}) {
  const flags = DRIVER_FLAG_KEYS.filter((f) => flagSupported(f, driver));
  if (flags.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {flags.map((flag) => (
        <DriverFlagOverride
          key={flag}
          flag={flag}
          driver={driver}
          value={value[flag]}
          onChange={(v) => {
            const next = { ...value };
            if (v === undefined) delete next[flag];
            else next[flag] = v;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}
