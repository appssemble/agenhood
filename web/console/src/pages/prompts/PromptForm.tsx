import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { fetchPrompt, useSavePrompt } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { CopyId } from "../../ui/CopyId";
import { Input, Textarea } from "../../ui/inputs";
import { extractVariables, resolve } from "../../lib/prompts";
import type { PromptVariable } from "../../api/types";

type VarMeta = { label: string; default: string };

export default function PromptForm() {
  const { id } = useParams();
  const editing = !!id;
  const nav = useNavigate();
  const toast = useToast();
  const save = useSavePrompt();

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  // Per-variable label/default metadata, keyed by variable name.
  const [meta, setMeta] = useState<Record<string, VarMeta>>({});
  const [loaded, setLoaded] = useState(!editing);

  useEffect(() => {
    if (!editing || !id) return;
    fetchPrompt(id).then((p) => {
      setName(p.name);
      setBody(p.body);
      setTags(p.tags);
      const m: Record<string, VarMeta> = {};
      p.variables.forEach((v) => { m[v.name] = { label: v.label ?? "", default: v.default ?? "" }; });
      setMeta(m);
      setLoaded(true);
    }).catch((err) => {
      toast.error("Couldn't load prompt", err instanceof ApiError ? err.message : undefined);
      nav("/prompts");
    });
  }, [editing, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const varNames = useMemo(() => extractVariables(body), [body]);

  const previewValues = useMemo(() => {
    const vals: Record<string, string> = {};
    varNames.forEach((n) => {
      const m = meta[n];
      vals[n] = (m?.default || m?.label || n);
    });
    return vals;
  }, [varNames, meta]);

  function addTag() {
    const t = tagDraft.trim();
    if (t && !tags.includes(t)) setTags([...tags, t]);
    setTagDraft("");
  }

  function buildVariables(): PromptVariable[] {
    return varNames.map((n) => ({ name: n, label: meta[n]?.label || "", default: meta[n]?.default || "" }));
  }

  async function onSave() {
    try {
      await save.mutateAsync({
        id,
        name: name.trim(),
        body,
        tags,
        variables: buildVariables(),
      });
      toast.success(editing ? "Prompt updated" : "Prompt created");
      nav("/prompts");
    } catch (err) {
      toast.error("Couldn't save prompt", err instanceof ApiError ? err.message : undefined);
    }
  }

  if (!loaded) return <div className="page"><div className="note">Loading…</div></div>;

  const canSave = !!name.trim() && !!body.trim() && !save.isPending;

  return (
    <div className="page">
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
        <Link to="/prompts" style={{ color: "var(--muted)" }}>Prompts</Link> / {editing ? "Edit" : "New prompt"}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {editing ? "Edit prompt" : "New prompt"}
          </div>
          {editing && id && <CopyId id={id} />}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link to="/prompts" className="btn btn-secondary btn-sm">Cancel</Link>
          <Button variant="primary" size="sm" onClick={onSave} disabled={!canSave}>Save prompt</Button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16, alignItems: "stretch", flex: 1, minHeight: 0 }}>
        {/* LEFT — fields */}
        <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", minHeight: 0 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }} htmlFor="p-name">Name</label>
          <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Weekly status report" style={{ marginTop: 6, marginBottom: 14 }} />

          <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>Tags</label>
          <div className="search-pill" style={{ marginTop: 6, marginBottom: 6, display: "flex", gap: 6, flexWrap: "wrap", borderRadius: 9 }}>
            {tags.map((t) => (
              <span key={t} className="tag" style={{ fontSize: 11 }}>
                {t}
                <button aria-label={`Remove ${t}`} onClick={() => setTags(tags.filter((x) => x !== t))} style={{ marginLeft: 4, border: "none", background: "none", cursor: "pointer", color: "var(--muted)" }}>×</button>
              </span>
            ))}
            <input
              aria-label="Add tag"
              placeholder="add tag…"
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              onBlur={addTag}
              style={{ border: "none", outline: "none", background: "transparent", fontSize: 12.5, minWidth: 80 }}
            />
          </div>

          <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)", display: "block", marginTop: 14 }} htmlFor="p-body">
            Prompt body <span style={{ color: "var(--muted-2)", fontWeight: 500 }}>— wrap variables in {"{{double braces}}"}</span>
          </label>
          <Textarea
            id="p-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            style={{ marginTop: 6, flex: 1, minHeight: 180, resize: "vertical", fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.65 }}
          />
          <div style={{ fontSize: 11, color: "var(--muted-2)", marginTop: 6, textAlign: "right" }}>
            {body.length} characters · {varNames.length} variable{varNames.length === 1 ? "" : "s"} detected
          </div>
        </div>

        {/* RIGHT — variables + preview */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: "var(--muted)", marginBottom: 10 }}>
              Detected variables
            </div>
            {varNames.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--muted-2)" }}>No variables yet. Add {"{{name}}"} to the body.</div>
            ) : varNames.map((n) => (
              <div key={n} style={{ border: "1px solid var(--border)", borderRadius: 9, padding: 10, marginBottom: 9 }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--p-700)", fontWeight: 600, marginBottom: 7 }}>{`{{${n}}}`}</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
                  <Input aria-label={`Label for ${n}`} placeholder="Label" value={meta[n]?.label ?? ""} onChange={(e) => setMeta({ ...meta, [n]: { label: e.target.value, default: meta[n]?.default ?? "" } })} />
                  <Input aria-label={`Default for ${n}`} placeholder="Default value" value={meta[n]?.default ?? ""} onChange={(e) => setMeta({ ...meta, [n]: { label: meta[n]?.label ?? "", default: e.target.value } })} />
                </div>
              </div>
            ))}
          </div>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: "var(--muted)", marginBottom: 10 }}>Preview</div>
            <div style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 9, padding: 11, fontSize: 12.5, lineHeight: 1.6, color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>
              {resolve(body, previewValues) || <span style={{ color: "var(--muted-2)" }}>Your prompt preview appears here.</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
