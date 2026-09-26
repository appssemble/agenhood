import { Checkbox, Tag } from "../ui";
import type { Template } from "../api/types";

// Per-task tools override. null ⇒ inherit the container's tools.
export function TaskToolsField({
  driverMeta, inherited, value, onChange,
}: {
  driverMeta: Template | undefined;
  inherited: string[];
  value: string[] | null;
  onChange: (v: string[] | null) => void;
}) {
  if (!driverMeta?.driver_template.tools_user_editable) return null;
  const current = value ?? inherited;
  function toggle(name: string) {
    onChange(current.includes(name) ? current.filter((t) => t !== name) : [...current, name]);
  }
  return (
    <div>
      <label className="check">
        <Checkbox
          checked={value !== null}
          onChange={() => onChange(value === null ? [...inherited] : null)}
          aria-label="Override tools for this task"
        />
        Override tools for this task
      </label>
      {value !== null && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: 8 }}>
          {driverMeta.available_tool_specs.map((t) => (
            <label key={t.name} className="check">
              <Checkbox
                checked={current.includes(t.name)}
                onChange={() => toggle(t.name)}
                aria-label={`task tool ${t.name}`}
              />
              {t.name}
              {t.requires_image_feature === "chromium" && (<Tag style={{ marginLeft: 4, fontSize: 10 }}>full</Tag>)}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
