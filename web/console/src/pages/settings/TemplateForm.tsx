import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTemplates, useTemplate, useSaveTemplate, useSkills, useMcpServers } from "../../api/queries";
import { useAuth } from "../../auth/useAuth";
import { useToast } from "../../components/Toast";
import { ApiError } from "../../api/client";
import { Field, Button, Note } from "../../ui";
import { ConfigFields } from "../../components/ConfigFields";
import { DriverPicker } from "../../components/DriverPicker";
import { assemblePrompt } from "../assemblePrompt";
import { driverLabel } from "../../lib/drivers";
import type { TemplateDraft, TemplateSavePayload, Template, AgentConfig, ToolSpec } from "../../api/types";

const EMPTY: TemplateDraft = {
  name: "", driver: "vanilla", model: "", system_prompt: "", system_prompt_mode: "augment",
  tools: [], context: { variables: {}, text: null, files: [] }, skills: [], mcp_servers: [], limits: {},
};

function fromTemplate(t: Template): TemplateDraft {
  return {
    name: t.name, driver: t.driver, model: t.model ?? "", system_prompt: t.system_prompt,
    system_prompt_mode: t.system_prompt_mode, tools: t.tools,
    context: t.context, skills: t.skills ?? [], mcp_servers: t.mcp_servers ?? [], limits: t.limits ?? {},
  };
}

export default function TemplateForm() {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const templatesQ = useTemplates();
  const skillsQ = useSkills();
  const mcpQ = useMcpServers();
  const existingQ = useTemplate(id ?? "");
  const save = useSaveTemplate();

  const [draft, setDraft] = useState<TemplateDraft | null>(id ? null : EMPTY);
  useEffect(() => { if (id && existingQ.data && !draft) setDraft(fromTemplate(existingQ.data)); }, [id, existingQ.data, draft]);

  const limits = user?.tenant?.limits;
  const builtins = templatesQ.data?.templates.filter((t) => t.is_builtin) ?? [];
  const driverMeta = useMemo(() => builtins.find((t) => t.driver === draft?.driver), [builtins, draft?.driver]);
  const enabledSkills = (skillsQ.data?.skills ?? []).filter((s) => s.enabled);
  const enabledMcpServers = (mcpQ.data?.mcp_servers ?? []).filter((s) => s.enabled);

  if (id && existingQ.isError) {
    return (
      <div className="page" style={{ maxWidth: 720 }}>
        <Note tone="amber">
          Couldn't load this template. It may have been deleted.{" "}
          <button className="btn btn-ghost btn-sm" onClick={() => navigate("/settings/templates")}>Back to templates</button>
        </Note>
      </div>
    );
  }

  if (!draft || !limits) return <div className="p-8 text-sm text-muted">Loading…</div>;

  function patch(p: Partial<TemplateDraft>) { setDraft((d) => (d ? { ...d, ...p } : d)); }

  // Changing the driver clears fields the new driver does not support, so the
  // saved template always matches the driver's capabilities.
  function changeDriver(driver: string) {
    const meta = builtins.find((t) => t.driver === driver);
    const editableTools = meta?.driver_template.tools_user_editable ?? true;
    const supportsContext = meta?.driver_template.supports_context ?? true;
    const skillDriver = driver === "opencode" || driver === "codex";
    setDraft((d) => (d ? {
      ...d, driver,
      tools: editableTools ? d.tools : [],
      context: supportsContext ? d.context : { variables: {}, text: null, files: [] },
      skills: skillDriver ? d.skills : [],
      mcp_servers: skillDriver ? d.mcp_servers : [],
    } : d));
  }

  async function onSave() {
    if (!draft) return;
    if (!draft.name.trim()) { toast.error("Name is required"); return; }
    const body: TemplateSavePayload = { ...draft, model: draft.model || null };
    try {
      await save.mutateAsync(id ? { id, body } : { body });
      toast.success(id ? "Template updated" : "Template created");
      navigate("/settings/templates");
    } catch (err) {
      toast.error("Couldn't save template", err instanceof ApiError ? err.message : undefined);
    }
  }

  // Live preview — mirrors the container Configuration screen so the assembled
  // prompt the agent will receive updates as you build the template.
  const toolSpecs: ToolSpec[] = driverMeta?.available_tool_specs ?? [];
  const editableTools = driverMeta?.driver_template.tools_user_editable ?? true;
  const isSkillDriver = draft.driver === "opencode" || draft.driver === "codex";
  const assembled = assemblePrompt(draft as unknown as AgentConfig, toolSpecs);

  // Highlight the user's prompt within the assembled scaffolding (augment mode).
  const userPrompt = draft.system_prompt;
  const userIndex = draft.system_prompt_mode !== "replace" && userPrompt
    ? assembled.indexOf(userPrompt) : -1;
  const beforeUser = userIndex >= 0 ? assembled.slice(0, userIndex) : assembled;
  const afterUser = userIndex >= 0 ? assembled.slice(userIndex + userPrompt.length) : "";

  return (
    <div className="responsive-editor responsive-split" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 1fr)", height: "100%", overflow: "hidden", background: "var(--surface)" }}>
      {/* LEFT — ordered build form */}
      <div className="responsive-editor-pane" style={{ overflow: "auto", padding: "22px 24px 28px", display: "flex", flexDirection: "column", gap: 18, borderRight: "1px solid var(--border)" }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {id ? "Edit template" : "New template"}
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>
            Name it, pick a driver, then shape its behavior. The preview shows what the agent will receive.
          </div>
        </div>

        {/* Name */}
        <Field label="Name" htmlFor="tpl-name">
          <input id="tpl-name" className="input fluid-w" aria-label="Name" value={draft.name}
            style={{ maxWidth: 460 }}
            onChange={(e) => patch({ name: e.target.value })} />
        </Field>

        {/* Driver — card picker */}
        <Field label="Driver">
          <DriverPicker value={draft.driver} drivers={limits.allowed_drivers} onChange={changeDriver} />
        </Field>

        {/* Shared driver-conditional fields */}
        <ConfigFields value={draft} driverMeta={driverMeta} enabledSkills={enabledSkills} enabledMcpServers={enabledMcpServers} onPatch={patch} />
      </div>

      {/* RIGHT — live preview + summary + actions */}
      <div className="responsive-editor-pane" style={{ display: "flex", flexDirection: "column", minHeight: 0, background: "var(--surface-2)" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Preview · what the agent receives</div>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>updates as you build</div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Summary */}
          <dl className="kv" style={{ margin: 0 }}>
            <dt>Driver</dt><dd className="mono">{driverLabel(draft.driver)}</dd>
            <dt>Model</dt><dd className="mono">{draft.model || "tenant default"}</dd>
            {editableTools && (<><dt>Tools</dt><dd>{draft.tools.length} enabled</dd></>)}
            {isSkillDriver && (<><dt>Skills</dt><dd>{(draft.skills ?? []).length} attached</dd></>)}
            {isSkillDriver && (<><dt>MCP servers</dt><dd>{(draft.mcp_servers ?? []).length} attached</dd></>)}
          </dl>

          {/* Assembled prompt */}
          {editableTools ? (
            <div data-testid="assembled-preview" style={{ fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65, whiteSpace: "pre-wrap", color: "var(--ink-2)" }}>
              {userIndex >= 0 ? (
                <>
                  <span style={{ color: "var(--muted-2)" }}>{beforeUser}</span>
                  <span style={{ background: "var(--p-200)", color: "var(--ink)", padding: "1px 4px", borderRadius: 3 }}>{userPrompt}</span>
                  <span style={{ color: "var(--muted-2)" }}>{afterUser}</span>
                </>
              ) : (
                <span>{assembled}</span>
              )}
            </div>
          ) : (
            <Note tone="default">
              The <span className="mono">{draft.driver}</span> driver manages its own system prompt and tools, so there is no assembled preview.
            </Note>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "12px 20px", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>
          <Button variant="secondary" size="md" onClick={() => navigate("/settings/templates")}>Cancel</Button>
          <Button variant="primary" size="md" onClick={onSave} disabled={save.isPending}>Save template</Button>
        </div>
      </div>
    </div>
  );
}
