import { Input } from "../ui";
import type { EnvVar } from "../api/types";

// Shared editor for per-container env vars (Configuration, CreateContainer,
// TemplateForm). A saved secret arrives with value === null (write-only):
// it renders masked; Replace switches it to an editable empty value, and an
// untouched masked row round-trips null ("keep the stored secret").
export function EnvVarsField({
  value,
  onChange,
}: {
  value: EnvVar[];
  onChange: (rows: EnvVar[]) => void;
}) {
  function patchRow(i: number, p: Partial<EnvVar>) {
    onChange(value.map((r, j) => (j === i ? { ...r, ...p } : r)));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {value.map((row, i) => {
        const savedSecret = row.secret && row.value === null;
        return (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1.4fr auto auto",
              gap: 10,
              alignItems: "center",
            }}
          >
            <Input
              aria-label={`Env name ${i + 1}`}
              placeholder="NAME"
              value={row.name}
              onChange={(e) => patchRow(i, { name: e.target.value.toUpperCase() })}
            />
            {savedSecret ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="tag" style={{ fontFamily: "var(--font-mono)" }}>••••••••</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => patchRow(i, { value: "" })}
                >
                  Replace
                </button>
              </div>
            ) : (
              <Input
                aria-label={`Env value ${i + 1}`}
                placeholder="value"
                type={row.secret ? "password" : "text"}
                value={row.value ?? ""}
                onChange={(e) => patchRow(i, { value: e.target.value })}
              />
            )}
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--ink-2)" }}>
              <input
                type="checkbox"
                aria-label={`Secret ${i + 1}`}
                checked={row.secret}
                disabled={savedSecret}
                onChange={(e) => patchRow(i, { secret: e.target.checked })}
              />
              Secret
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label={`Remove env var ${i + 1}`}
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        );
      })}
      <div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => onChange([...value, { name: "", value: "", secret: false }])}
        >
          + Add variable
        </button>
      </div>
    </div>
  );
}
