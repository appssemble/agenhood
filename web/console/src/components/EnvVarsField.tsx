import { useState } from "react";
import { Input } from "../ui";
import { Icons } from "../ui/Icon";
import type { EnvVar } from "../api/types";

// Shared editor for per-container env vars (Configuration, CreateContainer,
// TemplateForm). A saved secret arrives with value === null (write-only): its
// name is locked — the backend's keep-the-stored-secret round-trip matches by
// name, so renaming would orphan the ciphertext — and its value renders as a
// masked placeholder. Replace switches the row to an editable empty value; an
// untouched masked row round-trips null ("keep the stored secret").
export function EnvVarsField({
  value,
  onChange,
}: {
  value: EnvVar[];
  onChange: (rows: EnvVar[]) => void;
}) {
  // View-only reveal state for secret values being typed; keyed by row index,
  // cleared on removal so it can never carry over to a shifted row.
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  function patchRow(i: number, p: Partial<EnvVar>) {
    onChange(value.map((r, j) => (j === i ? { ...r, ...p } : r)));
  }
  function removeRow(i: number) {
    setRevealed({});
    onChange(value.filter((_, j) => j !== i));
  }

  return (
    <div className="envv">
      {value.length === 0 && <div className="envv-empty">No environment variables yet.</div>}
      {value.map((row, i) => {
        const savedSecret = row.secret && row.value === null;
        const shown = !!revealed[i];
        return (
          <div key={i} className="envv-row">
            <Input
              aria-label={`Env name ${i + 1}`}
              placeholder="VARIABLE_NAME"
              value={row.name}
              readOnly={savedSecret}
              title={savedSecret ? "Stored secret — remove and re-add to rename" : undefined}
              onChange={(e) => patchRow(i, { name: e.target.value.toUpperCase() })}
            />
            <div className="envv-val">
              {savedSecret ? (
                <>
                  {/* value="" is load-bearing: without it React reuses the DOM
                      node from the editable branch and the last typed plaintext
                      lingers visibly in the disabled input after a save. */}
                  <Input disabled aria-hidden="true" tabIndex={-1} value="" placeholder="••••••••  stored" />
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-label={`Replace secret value ${i + 1}`}
                    onClick={() => {
                      setRevealed((s) => ({ ...s, [i]: false }));
                      patchRow(i, { value: "" });
                    }}
                  >
                    <Icons.Refresh w={13} /> Replace
                  </button>
                </>
              ) : (
                <>
                  <Input
                    aria-label={`Env value ${i + 1}`}
                    placeholder={row.secret ? "secret value" : "value"}
                    type={row.secret && !shown ? "password" : "text"}
                    value={row.value ?? ""}
                    onChange={(e) => patchRow(i, { value: e.target.value })}
                  />
                  {row.secret && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm btn-icon"
                      aria-label={`${shown ? "Hide" : "Show"} secret value ${i + 1}`}
                      aria-pressed={shown}
                      title={shown ? "Hide value" : "Show value"}
                      onClick={() => setRevealed((s) => ({ ...s, [i]: !s[i] }))}
                    >
                      <Icons.Eye w={14} />
                    </button>
                  )}
                </>
              )}
            </div>
            <div className="envv-ctl">
              <label
                className="check"
                title={
                  savedSecret
                    ? "Stored secrets stay secret"
                    : "Encrypted at rest; the value becomes write-only after saving"
                }
              >
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
                className="btn btn-ghost btn-sm btn-icon"
                aria-label={`Remove env var ${i + 1}`}
                title="Remove"
                onClick={() => removeRow(i)}
              >
                <Icons.Trash w={14} />
              </button>
            </div>
          </div>
        );
      })}
      <div className="envv-foot">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => onChange([...value, { name: "", value: "", secret: false }])}
        >
          <Icons.Plus w={13} /> Add variable
        </button>
        <span className="envv-rules">Names: A–Z, 0–9, _ · secrets are encrypted and write-only</span>
      </div>
    </div>
  );
}
