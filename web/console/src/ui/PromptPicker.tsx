import { useMemo, useState } from "react";
import { usePrompts } from "../api/queries";
import { Button } from "./Button";
import { Icons } from "./Icon";
import { extractVariables, resolve } from "../lib/prompts";
import type { Prompt } from "../api/types";

export function PromptPicker({ open, onInsert, onClose }: {
  open: boolean;
  onInsert: (text: string) => void;
  onClose: () => void;
}) {
  // Only fetch once the picker is opened — it's mounted permanently in the task forms.
  const { data, isLoading } = usePrompts({ enabled: open });
  const prompts = useMemo(() => data?.prompts ?? [], [data]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return prompts;
    return prompts.filter((p) => p.name.toLowerCase().includes(q) || p.body.toLowerCase().includes(q));
  }, [prompts, query]);

  // Default selection: first visible prompt. If selectedId is set but filtered out, fall back to first visible.
  const selected: Prompt | null = useMemo(() => {
    if (selectedId && visible.some((p) => p.id === selectedId)) {
      return prompts.find((p) => p.id === selectedId) ?? null;
    }
    return visible[0] ?? null;
  }, [selectedId, prompts, visible]);

  // Effective values: the selected prompt's defaults, with explicit user input layered on top.
  const effectiveValues = useMemo(() => {
    if (!selected) return values;
    const seed: Record<string, string> = {};
    selected.variables.forEach((v) => { if (v.default) seed[v.name] = v.default; });
    return { ...seed, ...values };
  }, [selected, values]);

  const varNames = useMemo(() => (selected ? extractVariables(selected.body) : []), [selected]);

  function pick(p: Prompt) {
    setSelectedId(p.id);
    setValues({});
  }

  function labelFor(name: string): string {
    return selected?.variables.find((v) => v.name === name)?.label ?? name;
  }

  function doInsert() {
    if (!selected) return;
    onInsert(resolve(selected.body, effectiveValues));
    onClose();
  }

  if (!open) return null;

  return (
    <div role="dialog" aria-label="Use a prompt" style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(10,10,10,.34)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 680, maxWidth: "94%", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, boxShadow: "var(--sh-3)", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 18px", borderBottom: "1px solid var(--surface-3)" }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Use a prompt</div>
          <button aria-label="Close" onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 16 }}><Icons.Close w={16} /></button>
        </div>

        <div className="search-pill" style={{ margin: "14px 18px 4px" }}>
          <Icons.Search />
          <input aria-label="Search prompts" placeholder="Search prompts…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", height: 330 }}>
          <div style={{ borderRight: "1px solid var(--surface-3)", padding: 10, overflow: "auto" }}>
            {isLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 8 }}>Loading…</div>}
            {!isLoading && visible.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)", padding: 8 }}>No prompts.</div>}
            {visible.map((p) => {
              const active = selected?.id === p.id;
              return (
                <button key={p.id} onClick={() => pick(p)} style={{ display: "block", width: "100%", textAlign: "left", padding: "10px 11px", borderRadius: 9, marginBottom: 4, cursor: "pointer", border: active ? "1px solid rgba(135,130,13,.22)" : "1px solid transparent", background: active ? "var(--p-100)" : "transparent" }}>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{p.name}</div>
                  <div className="clamp-1" style={{ color: "var(--muted)", fontSize: 11.5, marginTop: 2 }}>{p.body}</div>
                </button>
              );
            })}
          </div>

          <div style={{ padding: "16px 18px", overflow: "auto" }}>
            {!selected ? (
              <div style={{ fontSize: 12, color: "var(--muted)" }}>Select a prompt.</div>
            ) : (
              <>
                {varNames.length > 0 && (
                  <>
                    <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", marginBottom: 8 }}>Fill in variables</div>
                    {varNames.map((n) => (
                      <div key={n} style={{ marginBottom: 12 }}>
                        <label htmlFor={`pv-${n}`} style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)", display: "block", marginBottom: 5 }}>
                          {labelFor(n)} <span style={{ fontFamily: "var(--font-mono)", color: "var(--p-700)" }}>{`{{${n}}}`}</span>
                        </label>
                        <input id={`pv-${n}`} aria-label={labelFor(n)} className="input" value={effectiveValues[n] ?? ""} onChange={(e) => { const v = e.target.value; setValues((prev) => ({ ...prev, [n]: v })); }} style={{ width: "100%" }} />
                      </div>
                    ))}
                  </>
                )}
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", margin: "6px 0 8px" }}>Live preview</div>
                <div style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 9, padding: 11, fontSize: 12.5, lineHeight: 1.55, color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>
                  {resolve(selected.body, effectiveValues)}
                </div>
              </>
            )}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, padding: "13px 18px", borderTop: "1px solid var(--surface-3)" }}>
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={doInsert} disabled={!selected}>Insert prompt</Button>
        </div>
      </div>
    </div>
  );
}
