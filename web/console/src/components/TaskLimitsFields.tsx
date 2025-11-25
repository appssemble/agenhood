import { Field } from "../ui";
import type { TenantLimits } from "../api/types";

// Per-task limit overrides shared by the form and chat layouts. A blank field
// inherits the container/tenant default (shown as the placeholder + hint).
export function TaskLimitsFields({
  supportsMaxIterations,
  iterDefault,
  tokensDefault,
  timeoutDefault,
  tenantLimits,
  maxIter,
  setMaxIter,
  maxTokens,
  setMaxTokens,
  timeoutS,
  setTimeoutS,
}: {
  supportsMaxIterations: boolean;
  iterDefault?: number | null;
  tokensDefault?: number | null;
  timeoutDefault?: number | null;
  tenantLimits?: TenantLimits;
  maxIter: number | null;
  setMaxIter: (v: number | null) => void;
  maxTokens: number | null;
  setMaxTokens: (v: number | null) => void;
  timeoutS: number | null;
  setTimeoutS: (v: number | null) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: supportsMaxIterations ? "1fr 1fr 1fr" : "1fr 1fr", gap: 12 }}>
      {supportsMaxIterations && (
        <Field label="Max iterations" hint={`default ${iterDefault ?? "—"} · ceiling ${tenantLimits?.default_max_iterations ?? "—"}`}>
          <input
            className="input num" type="number" min={1} inputMode="numeric" aria-label="Max iterations"
            value={maxIter ?? ""}
            placeholder={iterDefault != null ? String(iterDefault) : ""}
            onChange={(e) => setMaxIter(e.target.value === "" ? null : Number(e.target.value))}
          />
        </Field>
      )}
      <Field label="Max tokens" hint={`default ${tokensDefault?.toLocaleString() ?? "—"} · ceiling ${tenantLimits?.default_max_tokens?.toLocaleString() ?? "—"}`}>
        <input
          className="input num" type="number" min={1} inputMode="numeric" aria-label="Max tokens"
          value={maxTokens ?? ""}
          placeholder={tokensDefault != null ? String(tokensDefault) : ""}
          onChange={(e) => setMaxTokens(e.target.value === "" ? null : Number(e.target.value))}
        />
      </Field>
      <Field label="Timeout (s)" hint={`default ${timeoutDefault ?? "—"} · ceiling ${tenantLimits?.default_task_timeout_seconds ?? "—"}`}>
        <input
          className="input num" type="number" min={1} inputMode="numeric" aria-label="Timeout (s)"
          value={timeoutS ?? ""}
          placeholder={timeoutDefault != null ? String(timeoutDefault) : ""}
          onChange={(e) => setTimeoutS(e.target.value === "" ? null : Number(e.target.value))}
        />
      </Field>
    </div>
  );
}
