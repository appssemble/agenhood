import { Field, Textarea, Note } from "../ui";
import { Icons } from "../ui/Icon";
import type { OutputType } from "../api/types";

export type SchemaParse =
  | { ok: true; value?: Record<string, unknown> }
  | { ok: false; error: string };

/** Parse the schema textarea. Empty is valid (no schema). Must be a JSON object. */
export function parseSchema(text: string): SchemaParse {
  const t = text.trim();
  if (!t) return { ok: true, value: undefined };
  let v: unknown;
  try { v = JSON.parse(t); }
  catch (e) { return { ok: false, error: (e as Error).message }; }
  if (typeof v !== "object" || v === null || Array.isArray(v)) {
    return { ok: false, error: "Schema must be a JSON object." };
  }
  return { ok: true, value: v as Record<string, unknown> };
}

const EXAMPLE = `{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "items": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "required": ["summary"]
}`;

const OPTIONS: { value: OutputType; title: string; desc: string; icon: React.ReactNode }[] = [
  { value: "text", title: "Text", desc: "Final message as plain text", icon: <Icons.Terminal w={16} /> },
  { value: "files", title: "Files", desc: "Files written to the workspace", icon: <Icons.Folder w={16} /> },
  { value: "structured", title: "Structured", desc: "JSON matching a schema", icon: <Icons.Code w={16} /> },
];

export function OutputContractField({
  type, onTypeChange, schemaText, onSchemaTextChange, structuredSupported, driver,
}: {
  type: OutputType;
  onTypeChange: (t: OutputType) => void;
  schemaText: string;
  onSchemaTextChange: (s: string) => void;
  structuredSupported: boolean;
  driver: string;
}) {
  const parsed = parseSchema(schemaText);
  const empty = schemaText.trim() === "";

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>Output contract</div>
        <div style={{ fontSize: 11.5, color: "var(--muted)" }}>What the agent returns when the task completes</div>
      </div>

      <div className="oc-grid" role="group" aria-label="Output contract">
        {OPTIONS.map((o) => {
          const selected = type === o.value;
          const disabled = o.value === "structured" && !structuredSupported;
          return (
            <button
              key={o.value} type="button"
              className="oc-card" data-selected={selected}
              aria-pressed={selected} disabled={disabled}
              onClick={() => onTypeChange(o.value)}
            >
              <span className="oc-card-ico" aria-hidden>{o.icon}</span>
              <span style={{ minWidth: 0, flex: 1 }}>
                <span style={{ display: "block", fontWeight: 700, fontSize: 13 }}>{o.title}</span>
                <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{o.desc}</span>
              </span>
              {/* Fixed slot so selecting (which reveals the check) never resizes the card. */}
              <span aria-hidden style={{ width: 15, flexShrink: 0, display: "inline-flex", visibility: selected ? "visible" : "hidden" }}>
                <Icons.Check w={15} style={{ color: "var(--ink)" }} />
              </span>
            </button>
          );
        })}
      </div>

      {!structuredSupported && (
        <Note
          tone="amber"
          role="note"
          style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, lineHeight: 1.45 }}
        >
          <Icons.Info w={15} style={{ flexShrink: 0 }} />
          <span>
            Structured output isn't available — the <span className="mono">{driver}</span> driver doesn't support it.
          </span>
        </Note>
      )}

      {/* Contextual area for the selected mode */}
      <div style={{ marginTop: 10 }} aria-live="polite">
        {type === "structured" ? (
          <div style={{ display: "grid", gap: 8 }}>
            <Field
              label="Response schema"
              hint="A JSON Schema the response must conform to. Leave blank to let the model choose the shape."
              htmlFor="oc-schema"
            >
              <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                <button type="button" className="btn btn-ghost btn-sm" style={{ gap: 6 }} onClick={() => onSchemaTextChange(EXAMPLE)}>
                  <Icons.Sparkles w={13} /> Insert example
                </button>
                {!empty && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => onSchemaTextChange("")}>Clear</button>
                )}
              </div>
              <Textarea
                id="oc-schema" aria-label="Response schema" value={schemaText}
                onChange={(e) => onSchemaTextChange(e.target.value)}
                spellCheck={false} autoCapitalize="off" autoCorrect="off"
                placeholder={EXAMPLE}
                aria-invalid={!empty && !parsed.ok}
                style={{ minHeight: 180, fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.6 }}
              />
            </Field>
            <div
              style={{
                fontSize: 11.5, display: "inline-flex", alignItems: "center", gap: 6,
                color: empty ? "var(--muted)" : parsed.ok ? "var(--info-700)" : "var(--err-700)",
              }}
            >
              {empty ? (
                <span>The response will be free-form JSON.</span>
              ) : parsed.ok ? (
                <><Icons.Check w={13} /> <span>Valid JSON Schema</span></>
              ) : (
                <><Icons.Warn w={13} /> <span className="mono">{parsed.error}</span></>
              )}
            </div>
          </div>
        ) : (
          <div className="note">
            {type === "text"
              ? "The task returns the agent's final message as plain text."
              : "The task returns the files the agent created or changed in the workspace."}
          </div>
        )}
      </div>
    </div>
  );
}
