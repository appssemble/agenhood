import { Field, SegControl } from "../ui";
import { EFFORT_DRIVERS } from "../api/types";
import type { Effort } from "../api/types";

const EFFORT_SEG: { value: "" | Effort; label: string }[] = [
  { value: "", label: "Default" },
  { value: "low", label: "low" },
  { value: "medium", label: "medium" },
  { value: "high", label: "high" },
  { value: "max", label: "max" },
];

// Reasoning-effort selector shared by the submit form, chat Options panel and
// container/template configuration. Renders nothing for drivers whose CLI has
// no effort flag (the backend rejects the value there anyway). The default
// hint reads as a per-task override; config surfaces pass their own.
export function EffortField({
  driver,
  value,
  onChange,
  hint = "Reasoning effort for this task · Default inherits the container setting",
}: {
  driver: string;
  value: Effort | null;
  onChange: (v: Effort | null) => void;
  hint?: string;
}) {
  if (!EFFORT_DRIVERS.includes(driver)) return null;
  return (
    <Field label="Effort" hint={hint}>
      <SegControl<"" | Effort>
        className="seg-fit"
        options={EFFORT_SEG}
        value={value ?? ""}
        onChange={(v) => onChange(v === "" ? null : v)}
      />
    </Field>
  );
}
