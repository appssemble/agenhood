import { useMemo, useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { useContainer, useTemplates, useSaveConfig, useSkills, useMcpServers, useContainerEnv, useUpdateEnvVars } from "../api/queries";
import { useAuth } from "../auth/useAuth";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import { assemblePrompt } from "./assemblePrompt";
import { Field, Tag, Note, Dropdown } from "../ui";
import { Icons } from "../ui/Icon";
import { ConfigFields } from "../components/ConfigFields";
import { EnvVarsField } from "../components/EnvVarsField";
import { EFFORT_DRIVERS } from "../api/types";
import type { AgentConfig, EnvVar, Template, ToolSpec } from "../api/types";

export default function Configuration() {
  const { cid } = useParams<{ cid: string }>();
  const { user } = useAuth();
  const toast = useToast();
  const containerQ = useContainer(cid!);
  const templatesQ = useTemplates();
  const save = useSaveConfig(cid!);
  const skillsQ = useSkills();
  const mcpQ = useMcpServers();
  const envQ = useContainerEnv(cid!);
  const saveEnv = useUpdateEnvVars(cid!);

  const [draft, setDraft] = useState<AgentConfig | null>(null);
  useEffect(() => { if (containerQ.data && !draft) setDraft(containerQ.data.config); }, [containerQ.data, draft]);
  const [envDraft, setEnvDraft] = useState<EnvVar[] | null>(null);
  useEffect(() => { if (envQ.data && envDraft === null) setEnvDraft(envQ.data); }, [envQ.data, envDraft]);

  const limits = user?.tenant?.limits;
  const builtins = templatesQ.data?.templates.filter((t) => t.is_builtin) ?? [];
  const driverMeta: Template | undefined = useMemo(
    () => builtins.find((t) => t.driver === draft?.driver),
    [builtins, draft?.driver]
  );
  const toolSpecs: ToolSpec[] = driverMeta?.available_tool_specs ?? [];
  const variant = containerQ.data?.image_variant ?? "full";

  if (!draft || !limits) return <div className="p-8 text-sm text-muted">Loading…</div>;

  const configDirty = JSON.stringify(draft) !== JSON.stringify(containerQ.data?.config);
  const envDirty = envDraft !== null && JSON.stringify(envDraft) !== JSON.stringify(envQ.data ?? []);
  const dirty = configDirty || envDirty;
  const editableTools = driverMeta?.driver_template.tools_user_editable ?? true;
  // Only the vanilla driver runs the host-managed reason→act loop; opencode,
  // codex, and claude-code drive their own control flow, so the iteration cap doesn't apply.
  const supportsMaxIterations = draft.driver === "vanilla";
  const enabledSkills = (skillsQ.data?.skills ?? []).filter((s) => s.enabled);
  const enabledMcpServers = (mcpQ.data?.mcp_servers ?? []).filter((s) => s.enabled);
  const assembled = assemblePrompt(draft, toolSpecs);

  // Split assembled prompt into scaffold vs user portion for highlighting
  const userPrompt = draft.system_prompt;
  const userIndex = draft.system_prompt_mode !== "replace"
    ? assembled.indexOf(userPrompt)
    : -1;
  const beforeUser = userIndex >= 0 ? assembled.slice(0, userIndex) : assembled;
  const afterUser = userIndex >= 0 ? assembled.slice(userIndex + userPrompt.length) : "";

  function patch(p: Partial<AgentConfig>) { setDraft((d) => (d ? { ...d, ...p } : d)); }
  const variantWarnings = draft.tools
    .map((name) => toolSpecs.find((t) => t.name === name))
    .filter((t): t is ToolSpec => !!t && t.requires_image_feature === "chromium" && variant === "slim");

  const dirtyCount = (() => {
    const orig = containerQ.data?.config;
    if (!orig) return 0;
    let n = 0;
    if (orig.driver !== draft.driver) n++;
    if (orig.model !== draft.model) n++;
    if ((orig.effort ?? null) !== (draft.effort ?? null)) n++;
    if (orig.system_prompt !== draft.system_prompt) n++;
    if (orig.system_prompt_mode !== draft.system_prompt_mode) n++;
    if (JSON.stringify(orig.tools) !== JSON.stringify(draft.tools)) n++;
    if (JSON.stringify(orig.context) !== JSON.stringify(draft.context)) n++;
    if (JSON.stringify(orig.skills ?? []) !== JSON.stringify(draft.skills ?? [])) n++;
    if (JSON.stringify(orig.mcp_servers ?? []) !== JSON.stringify(draft.mcp_servers ?? [])) n++;
    if ((orig.max_iterations ?? null) !== (draft.max_iterations ?? null)) n++;
    if ((orig.max_tokens ?? null) !== (draft.max_tokens ?? null)) n++;
    if ((orig.timeout_seconds ?? null) !== (draft.timeout_seconds ?? null)) n++;
    if (envDirty) n++;
    return n;
  })();

  async function onSave() {
    try {
      if (configDirty) await save.mutateAsync(draft!);
      if (envDirty && envDraft) await saveEnv.mutateAsync(envDraft);
      toast.success("Config saved. Applies to the next task");
    } catch (err) {
      toast.error("Couldn't save config", err instanceof ApiError ? err.message : undefined);
    }
  }


  return (
    <div
      className="grow responsive-editor responsive-split"
      style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22, overflow: "hidden" }}
    >
      {/* LEFT PANE — editor. No left padding: the shared container layout already
          insets every section by 22px, so adding more here over-indents only this one.
          The grid gap (not a border) separates it from the preview card on the right. */}
      <div className="responsive-editor-pane" style={{ overflow: "auto", padding: "0 0 22px 0" }}>
        {/* Unsaved-changes banner */}
        {dirty && (
          <div style={{ paddingTop: 12, paddingBottom: 0 }}>
            <div
              className="confirm-bar stack"
              style={{ background: "var(--p-100)", borderColor: "var(--p-300)", color: "var(--ink)" }}
            >
              <div className="msg">
                <Icons.Info />
                <span>
                  <b>{dirtyCount} unsaved {dirtyCount === 1 ? "change" : "changes"}</b> · applies to the <b>next task</b> <span style={{ color: "var(--muted)" }}>(in-flight tasks keep their setup)</span>
                </span>
              </div>
              <div className="actions">
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => { setDraft(containerQ.data!.config); setEnvDraft(envQ.data ?? []); }}
                >
                  Discard
                </button>
                <button className="btn btn-dark btn-sm" onClick={onSave}>Save</button>
              </div>
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Setup card — driver, image variant, and per-container task limits. */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {/* Driver / Variant row */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 14, alignItems: "start" }}>
              <Field label="Driver" htmlFor="cfg-driver">
                <Dropdown
                  id="cfg-driver"
                  value={draft.driver}
                  onChange={(v) => patch({ driver: v, ...(EFFORT_DRIVERS.includes(v) ? {} : { effort: null }) })}
                  options={limits.allowed_drivers.map((d) => ({ value: d, label: d }))}
                />
              </Field>
              {/* Image variant is fixed at container creation — shown read-only. */}
              <Field label="Image variant" hint="Set at creation">
                <div style={{ paddingTop: 7 }}>
                  <Tag aria-label="image variant">{variant}</Tag>
                </div>
              </Field>
            </div>

            {/* Per-container task-limit overrides. Blank = inherit the tenant
                default (shown as the placeholder); ceilings are enforced on save. */}
            <div style={{ display: "grid", gridTemplateColumns: supportsMaxIterations ? "1fr 1fr 1fr" : "1fr 1fr", gap: 14 }}>
              {supportsMaxIterations && (
                <Field label="Max iterations" hint="Blank = tenant default · caps the agent's reason→act steps">
                  <input
                    className="input num" type="number" min={1} inputMode="numeric" aria-label="Max iterations"
                    value={draft.max_iterations ?? ""}
                    placeholder={String(limits.default_max_iterations)}
                    onChange={(e) => patch({ max_iterations: e.target.value === "" ? null : Number(e.target.value) })}
                  />
                </Field>
              )}
              <Field label="Max tokens" hint={`Blank = tenant default (${limits.default_max_tokens?.toLocaleString()})`}>
                <input
                  className="input num" type="number" min={1} inputMode="numeric" aria-label="Max tokens"
                  value={draft.max_tokens ?? ""}
                  placeholder={String(limits.default_max_tokens)}
                  onChange={(e) => patch({ max_tokens: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </Field>
              <Field label="Timeout (s)" hint={`Blank = tenant default (${limits.default_task_timeout_seconds}s)`}>
                <input
                  className="input num" type="number" min={1} inputMode="numeric" aria-label="Timeout (s)"
                  value={draft.timeout_seconds ?? ""}
                  placeholder={String(limits.default_task_timeout_seconds)}
                  onChange={(e) => patch({ timeout_seconds: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </Field>
            </div>
          </div>

          {/* Shared driver-conditional fields */}
          <ConfigFields
            value={draft}
            driverMeta={driverMeta}
            enabledSkills={enabledSkills}
            enabledMcpServers={enabledMcpServers}
            onPatch={patch}
            variantWarning={variantWarnings.length > 0 ? (
              <Note tone="amber" style={{ marginTop: 10 }}>
                {variantWarnings.map((t) => t.name).join(", ")} need the full image variant, but this container is slim. Recreate it as full or disable these tools.
              </Note>
            ) : undefined}
          />

          {/* Per-container env vars for the agent process. Applies to the next
              task, like every other config change; secrets are write-only. */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Field
              label="Environment variables"
              hint="Available to the agent's processes on the next task · secret values are write-only"
            >
              <EnvVarsField value={envDraft ?? []} onChange={setEnvDraft} />
            </Field>
          </div>
        </div>
      </div>

      {/* RIGHT PANE — sticky assembled-prompt preview, styled as a card. */}
      <div
        className="responsive-editor-pane"
        style={{
          overflow: "auto",
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-3)",
          marginBottom: 22,
        }}
      >
        <div
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "var(--surface)",
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ink)", flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>Assembled prompt · what the agent receives</div>
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>read-only · updates as you edit</div>
          </div>
          <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}>
            <Icons.Copy /> Copy
          </button>
        </div>

        {editableTools ? (
          <div
            data-testid="assembled-preview"
            style={{
              padding: 20,
              fontFamily: "var(--font-mono)",
              fontSize: 12.5,
              lineHeight: 1.65,
              whiteSpace: "pre-wrap",
              color: "var(--ink-2)",
            }}
          >
            {draft.system_prompt_mode !== "replace" && userIndex >= 0 ? (
              <>
                <span style={{ color: "var(--muted-2)" }}>{beforeUser}</span>
                <span
                  style={{
                    background: "var(--p-200)",
                    color: "var(--ink)",
                    padding: "1px 4px",
                    borderRadius: 3,
                  }}
                >
                  {userPrompt}
                </span>
                <span style={{ color: "var(--muted-2)" }}>{afterUser}</span>
              </>
            ) : (
              <span>{assembled}</span>
            )}
          </div>
        ) : (
          <div
            data-testid="assembled-preview"
            style={{ padding: 20, fontSize: 13, color: "var(--muted)" }}
          >
            This driver manages its own system prompt, so no preview is available.
          </div>
        )}
      </div>
    </div>
  );
}
