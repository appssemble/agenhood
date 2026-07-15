import { Link } from "react-router-dom";
import { Pill } from "../../../ui/Pill";
import { STEP_PILL_TONE, type StepDetailVM } from "./derive";
import { formatDate } from "../../../lib/format";

const SECLABEL: React.CSSProperties = {
  fontSize: 11, fontWeight: 800, letterSpacing: "0.09em",
  textTransform: "uppercase", color: "var(--muted-2)",
};

export function StepDetailPanel({ vm }: { vm: StepDetailVM }) {
  return (
    <div style={{ borderTop: "1px solid var(--border)", background: "var(--surface-2)", padding: 16, borderRadius: "0 0 var(--r-3) var(--r-3)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ fontSize: 15, fontWeight: 800 }}>
            Step {vm.index + 1} · {vm.promptName}
          </span>
          {vm.status && (
            <Pill tone={STEP_PILL_TONE[vm.status]}>
              {vm.status}{vm.durationLabel ? ` · ${vm.durationLabel}` : ""}
            </Pill>
          )}
        </div>
        {vm.taskLink && (
          <Link to={vm.taskLink} className="btn btn-secondary btn-sm">Open task ↗</Link>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <div>
          <div style={{ ...SECLABEL, marginBottom: 8 }}>Step</div>
          <dl className="kv">
            <dt>Prompt</dt>
            <dd>{vm.promptName} <span className="id">{vm.promptId}</span></dd>
            <dt>Container</dt>
            <dd>{vm.containerName} <span className="id">{vm.containerId}</span></dd>
            <dt>Started</dt>
            <dd>{vm.startedAt ? formatDate(vm.startedAt) : "—"}</dd>
            <dt>Duration</dt>
            <dd>{vm.durationLabel ?? "—"}</dd>
            <dt>Passed on</dt>
            <dd>{vm.transferLabel ?? "—"}</dd>
          </dl>

          {vm.variables.length > 0 && (
            <>
              <div style={{ ...SECLABEL, margin: "16px 0 8px" }}>Variables</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {vm.variables.map(([k, v]) => (
                  <span key={k} className="tag" style={{ fontSize: 11, background: "var(--p-100)", color: "var(--p-700)" }}>
                    {k} = {v || "∅"}
                  </span>
                ))}
              </div>
            </>
          )}

          {vm.errorMessage && (
            <div className="note" style={{ marginTop: 16, color: "var(--err-700)", background: "var(--err-100)", padding: "8px 10px", borderRadius: "var(--r-2)", fontSize: 12.5 }}>
              {vm.errorMessage}
            </div>
          )}
        </div>

        <div>
          <div style={{ ...SECLABEL, marginBottom: 8 }}>Resolved prompt</div>
          <pre style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--r-2)", padding: "11px 13px", fontSize: 11.5, lineHeight: 1.55, color: "var(--ink-2)", whiteSpace: "pre-wrap", margin: 0, fontFamily: "var(--font-mono)" }}>
            {vm.resolvedBody}
          </pre>
        </div>
      </div>
    </div>
  );
}
