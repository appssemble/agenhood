import type { DropdownOption } from "../ui/Dropdown";

// Preset choices between the control plane's configured bounds (256m-8g,
// 0.25-4 CPU) — mirrors AGENT_MEM_LIMIT_MIN/MAX and AGENT_CPUS_MIN/MAX.
export const MEM_OPTIONS: DropdownOption[] = [
  { value: "256m", label: "256 MB" },
  { value: "512m", label: "512 MB" },
  { value: "1g", label: "1 GB" },
  { value: "2g", label: "2 GB" },
  { value: "4g", label: "4 GB" },
  { value: "8g", label: "8 GB" },
];

export const CPU_OPTIONS: DropdownOption[] = [
  { value: "0.25", label: "0.25 CPU" },
  { value: "0.5", label: "0.5 CPU" },
  { value: "1", label: "1 CPU" },
  { value: "2", label: "2 CPUs" },
  { value: "4", label: "4 CPUs" },
];

/** Make sure `value` is selectable even when it isn't one of the standard
 * presets (e.g. a value set before these presets existed, or directly via the
 * API) — inserted first and labeled distinctly so it doesn't read as a plain
 * preset. */
export function withCurrentValue(options: DropdownOption[], value: string): DropdownOption[] {
  if (!value || options.some((o) => o.value === value)) return options;
  return [{ value, label: `${value} (current)` }, ...options];
}
