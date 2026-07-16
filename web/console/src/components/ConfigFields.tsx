import type { ReactNode } from "react";
import { Field, Textarea, Checkbox, Tag, Note, SegControl } from "../ui";
import { Icons } from "../ui/Icon";
import { EffortField } from "./EffortField";
import { ModelPicker } from "./ModelPicker";
import { EFFORT_DRIVERS } from "../api/types";
import type { ContextSpec, SystemPromptMode, Template, ToolSpec, Skill, McpServer, Effort } from "../api/types";

export interface ConfigFieldsValue {
  driver: string;
  model: string;
  system_prompt: string;
  system_prompt_mode: SystemPromptMode;
  tools: string[];
  context: ContextSpec;
  skills?: string[];
  mcp_servers?: string[];
  effort?: Effort | null;
}

// A bordered area with an icon + title header and a padded body. Used for every
// config section so the form reads as a scannable stack of cards.
function SectionCard({
  icon: Glyph, title, hint, right, children,
}: {
  icon: (p: { w?: number }) => ReactNode;
  title: string;
  hint?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="section-card">
      <div className="section-card-head">
        <span className="section-card-ico"><Glyph w={15} /></span>
        <div className="section-card-titles">
          <span className="section-card-title">{title}</span>
          {hint && <span className="section-card-hint">{hint}</span>}
        </div>
        {right && <div className="spacer">{right}</div>}
      </div>
      <div className="section-card-body">{children}</div>
    </div>
  );
}

export function ConfigFields({
  value, driverMeta, enabledSkills, enabledMcpServers, onPatch, variantWarning,
}: {
  value: ConfigFieldsValue;
  driverMeta: Template | undefined;
  enabledSkills: Skill[];
  enabledMcpServers: McpServer[];
  onPatch: (p: Partial<ConfigFieldsValue>) => void;
  variantWarning?: ReactNode;
}) {
  const toolSpecs: ToolSpec[] = driverMeta?.available_tool_specs ?? [];
  const editableTools = driverMeta?.driver_template.tools_user_editable ?? true;
  const supportsContext = driverMeta?.driver_template.supports_context ?? true;
  const legacySkillDriver =
    value.driver === "opencode" || value.driver === "codex" || value.driver === "claude-code";
  const supportsSkills = driverMeta?.capabilities?.supports_skills ?? legacySkillDriver;
  const supportsMcp = driverMeta?.capabilities?.supports_mcp ?? legacySkillDriver;

  function toggleTool(name: string) {
    const has = value.tools.includes(name);
    onPatch({ tools: has ? value.tools.filter((t) => t !== name) : [...value.tools, name] });
  }
  function toggleSkill(id: string) {
    const cur = value.skills ?? [];
    const has = cur.includes(id);
    onPatch({ skills: has ? cur.filter((s) => s !== id) : [...cur, id] });
  }
  function toggleMcp(id: string) {
    const cur = value.mcp_servers ?? [];
    const has = cur.includes(id);
    onPatch({ mcp_servers: has ? cur.filter((s) => s !== id) : [...cur, id] });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Model */}
      <SectionCard icon={Icons.Cpu} title="Model">
        <ModelPicker driver={value.driver} value={value.model} onChange={(m) => onPatch({ model: m })} />
        {EFFORT_DRIVERS.includes(value.driver) && (
          <div style={{ marginTop: 14 }}>
            <EffortField
              driver={value.driver}
              value={value.effort ?? null}
              onChange={(v) => onPatch({ effort: v })}
              hint="Reasoning effort passed to the CLI · Default keeps the model's own"
            />
          </div>
        )}
      </SectionCard>

      {/* System prompt — prompt-mode control lives in the header */}
      <SectionCard
        icon={Icons.Terminal}
        title="System prompt"
        hint="Mode controls whether the runtime wraps this in default scaffolding."
        right={
          <SegControl<"augment" | "replace">
            value={value.system_prompt_mode as "augment" | "replace"}
            onChange={(v) => onPatch({ system_prompt_mode: v })}
            options={[
              { value: "augment", label: "Augment" },
              { value: "replace", label: (<>Replace <span style={{ color: "var(--err-700)", marginLeft: 4 }}>⚠</span></>) },
            ]}
          />
        }
      >
        <Textarea
          aria-label="System prompt"
          value={value.system_prompt}
          onChange={(e) => onPatch({ system_prompt: e.target.value })}
          style={{ minHeight: 110, fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.6 }}
        />
        {value.system_prompt_mode === "replace" ? (
          <Note tone="amber" style={{ fontSize: 11.5, padding: "6px 10px", marginTop: 10 }}>
            ⚠ Replace sends your text verbatim. You own the tool/done instructions.
          </Note>
        ) : (
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
            Your text is wrapped by the runtime's default scaffolding.
          </div>
        )}
      </SectionCard>

      {/* Tools — driver-aware */}
      {editableTools ? (
        <SectionCard icon={Icons.Wrench} title="Tools" hint={`${value.driver} driver · ${toolSpecs.length} available`}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
            {toolSpecs.map((t) => (
              <label key={t.name} className="check">
                <Checkbox checked={value.tools.includes(t.name)} onChange={() => toggleTool(t.name)} aria-label={t.name} />
                {t.name}
                {t.requires_image_feature === "chromium" && (<Tag style={{ marginLeft: 4, fontSize: 10 }}>full</Tag>)}
              </label>
            ))}
          </div>
          {variantWarning}
          <div className="note" style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "flex-start" }}>
            <Icons.Info />
            <div>
              <b>If you switch to <span className="mono">opencode</span>, <span className="mono">codex</span>, or <span className="mono">claude-code</span></b>, this picker is hidden,
              because these drivers manage their own tools and context.
            </div>
          </div>
        </SectionCard>
      ) : (
        <Note tone="default">
          The <span className="mono">{value.driver}</span> driver manages its own tools and context, so the tool picker is hidden.
        </Note>
      )}

      {/* Standing context — only when driver supports it */}
      {supportsContext && (
        <SectionCard icon={Icons.File} title="Standing context">
          <Field label="Inline text">
            <Textarea
              value={value.context.text ?? ""}
              onChange={(e) => onPatch({ context: { ...value.context, text: e.target.value || null } })}
              style={{ fontSize: 13 }}
            />
          </Field>
        </SectionCard>
      )}

      {/* Skills — gated on driver capability, falling back to the legacy driver list */}
      {supportsSkills && (
        <SectionCard icon={Icons.Puzzle} title="Skills" hint={`${value.driver} · ${enabledSkills.length} available`}>
          {enabledSkills.length === 0 ? (
            <Note tone="default">
              No skills yet. Create them under <span className="mono">Settings → Skills</span>.
            </Note>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {enabledSkills.map((s) => (
                <label key={s.id} className="check" title={s.description}>
                  <Checkbox checked={(value.skills ?? []).includes(s.id)} onChange={() => toggleSkill(s.id)} aria-label={s.name} />
                  {s.name}
                </label>
              ))}
            </div>
          )}
        </SectionCard>
      )}

      {/* MCP servers — gated on driver capability, falling back to the legacy driver list */}
      {supportsMcp && (
        <SectionCard icon={Icons.Web} title="MCP servers" hint={`${value.driver} · ${enabledMcpServers.length} available`}>
          {enabledMcpServers.length === 0 ? (
            <Note tone="default">
              No MCP servers yet. Create them under <span className="mono">Settings → MCP servers</span>.
            </Note>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {enabledMcpServers.map((s) => (
                <label key={s.id} className="check" title={s.description}>
                  <Checkbox checked={(value.mcp_servers ?? []).includes(s.id)} onChange={() => toggleMcp(s.id)} aria-label={s.name} />
                  {s.name}
                </label>
              ))}
            </div>
          )}
        </SectionCard>
      )}
    </div>
  );
}
