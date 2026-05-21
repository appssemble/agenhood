import { useMemo, useState } from "react";
import { useSavePrompt } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Input, Textarea } from "../../ui/inputs";
import { extractVariables, resolve } from "../../lib/prompts";
import { buildPromptVariables, type VarMeta } from "./builderUtils";
import type { Prompt } from "../../api/types";

function metaFromPrompt(p?: Prompt): Record<string, VarMeta> {
  const m: Record<string, VarMeta> = {};
  p?.variables.forEach((v) => { m[v.name] = { label: v.label ?? "", default: v.default ?? "" }; });
  return m;
}

export function InlinePromptEditor({
  mode, prompt, initialName = "", usageCount, onSaved, onCancel,
}: {
  mode: "edit" | "create";
  prompt?: Prompt;
  initialName?: string;
  usageCount: number;
  onSaved: (prompt: Prompt) => void;
  onCancel: () => void;
}) {
  const save = useSavePrompt();
  const toast = useToast();

  const [name, setName] = useState(initialName);
  const [body, setBody] = useState(prompt?.body ?? "");
  const [meta, setMeta] = useState<Record<string, VarMeta>>(() => metaFromPrompt(prompt));

  const varNames = useMemo(() => extractVariables(body), [body]);
  const previewValues = useMemo(() => {
    const vals: Record<string, string> = {};
    varNames.forEach((n) => { const m = meta[n]; vals[n] = m?.default || m?.label || n; });
    return vals;
  }, [varNames, meta]);

  function revert() {
    setBody(prompt?.body ?? "");
    setMeta(metaFromPrompt(prompt));
  }

  async function onSave() {
    try {
      const variables = buildPromptVariables(varNames, meta);
      const saved = mode === "create"
        ? await save.mutateAsync({ name: name.trim(), body, tags: [], variables })
        : await save.mutateAsync({ id: prompt!.id, name: prompt!.name, body, tags: prompt!.tags, variables });
      toast.success(mode === "create" ? "Prompt created" : "Prompt updated");
      onSaved(saved);
    } catch (err) {
      toast.error(
        mode === "create" ? "Couldn't create prompt" : "Couldn't save prompt",
        err instanceof ApiError ? err.message : undefined,
      );
    }
  }

  const baseMeta = metaFromPrompt(prompt); // baseline label/default for the loaded prompt
  const metaDirty = (() => {
    const keys = new Set([...Object.keys(meta), ...Object.keys(baseMeta)]);
    for (const k of keys) {
      if ((meta[k]?.label ?? "") !== (baseMeta[k]?.label ?? "")) return true;
      if ((meta[k]?.default ?? "") !== (baseMeta[k]?.default ?? "")) return true;
    }
    return false;
  })();
  const dirty = mode === "create" || body !== (prompt?.body ?? "") || metaDirty;

  const canSave = !!body.trim() && !save.isPending && (mode === "create" ? !!name.trim() : dirty);

  return (
    <div className="wfb-prompt">
      {mode === "edit" && (
        <div
          className="wfb-prompt-warn"
          style={{
            background: usageCount > 1 ? "var(--warn-100)" : "var(--surface-3)",
            color: usageCount > 1 ? "var(--warn-700)" : "var(--muted)",
            border: `1px solid ${usageCount > 1 ? "rgba(217,138,43,.22)" : "var(--border)"}`,
          }}
        >
          Editing the shared prompt <b>{prompt?.name}</b> — changes apply to every workflow that uses it
          {usageCount > 0 ? ` (used by ${usageCount} workflow${usageCount === 1 ? "" : "s"}).` : "."}
        </div>
      )}

      {mode === "create" && (
        <div>
          <label className="wfb-prompt-lab" htmlFor="np-name">Name</label>
          <Input id="np-name" aria-label="New prompt name" value={name}
            onChange={(e) => setName(e.target.value)} placeholder="e.g. Draft release notes" />
        </div>
      )}

      <div>
        <label className="wfb-prompt-lab" htmlFor="np-body">
          Prompt body <span style={{ color: "var(--muted-2)", fontWeight: 500 }}>— wrap variables in {"{{double braces}}"}</span>
        </label>
        <Textarea id="np-body" aria-label="Prompt body" value={body}
          onChange={(e) => setBody(e.target.value)}
          style={{ minHeight: 120, fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.6, resize: "vertical" }} />
        <div style={{ fontSize: 11, color: "var(--muted-2)", marginTop: 5, textAlign: "right" }}>
          {body.length} characters · {varNames.length} variable{varNames.length === 1 ? "" : "s"} detected
        </div>
      </div>

      {varNames.length > 0 && (
        <div>
          <div className="wfb-vars-lab">Prompt variables — label &amp; default</div>
          <div className="wfb-vars-grid">
            {varNames.map((n) => (
              <div key={n} style={{ border: "1px solid var(--border)", borderRadius: 9, padding: 9, background: "var(--surface)" }}>
                <div className="wfb-var-lab">{`{{${n}}}`}</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  <Input aria-label={`Label for ${n}`} placeholder="Label" value={meta[n]?.label ?? ""}
                    onChange={(e) => setMeta({ ...meta, [n]: { label: e.target.value, default: meta[n]?.default ?? "" } })} />
                  <Input aria-label={`Default for ${n}`} placeholder="Default" value={meta[n]?.default ?? ""}
                    onChange={(e) => setMeta({ ...meta, [n]: { label: meta[n]?.label ?? "", default: e.target.value } })} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="wfb-vars-lab">Preview</div>
        <div className="wfb-prompt-preview">
          {resolve(body, previewValues) || <span style={{ color: "var(--muted-2)" }}>Your prompt preview appears here.</span>}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        {mode === "edit"
          ? <Button variant="secondary" size="sm" onClick={revert} disabled={save.isPending}>Revert</Button>
          : <Button variant="secondary" size="sm" onClick={onCancel} disabled={save.isPending}>Cancel</Button>}
        <Button variant="primary" size="sm" onClick={onSave} disabled={!canSave}>
          {save.isPending && <span className="spinner" style={{ width: 11, height: 11, marginRight: 2 }} />}
          {mode === "create" ? "Create prompt" : "Save prompt"}
        </Button>
      </div>
    </div>
  );
}
