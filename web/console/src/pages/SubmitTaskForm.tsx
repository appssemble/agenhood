import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Tag, Textarea } from "../ui";
import { Icons } from "../ui/Icon";
import { EffortField } from "../components/EffortField";
import { OutputContractField } from "../components/OutputContractField";
import { TaskLimitsFields } from "../components/TaskLimitsFields";
import { PromptPicker } from "../ui/PromptPicker";
import { appendPrompt } from "../lib/prompt";
import { EFFORT_DRIVERS } from "../api/types";
import type { AgentConfig, Effort, OutputType, TaskSummary, TenantLimits } from "../api/types";

// Classic form layout for submitting a task. Extracted unchanged from the
// original SubmitTask screen; the parent owns all state and submission.
export function SubmitTaskForm({
  cid,
  config,
  imageVariant,
  recentTasks,
  prompt,
  setPrompt,
  prefillId,
  onClear,
  onPickRecent,
  outputType,
  setOutputType,
  schemaText,
  setSchemaText,
  structuredSupported,
  schemaBlocksSubmit,
  onSubmit,
  submitting,
  effort,
  onEffortChange,
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
  cid: string;
  config: AgentConfig;
  imageVariant: string;
  recentTasks: TaskSummary[];
  prompt: string;
  setPrompt: (v: string) => void;
  prefillId: string | null;
  onClear: () => void;
  onPickRecent: (prompt: string, taskId: string) => void;
  outputType: OutputType;
  setOutputType: (v: OutputType) => void;
  schemaText: string;
  setSchemaText: (v: string) => void;
  structuredSupported: boolean;
  schemaBlocksSubmit: boolean;
  onSubmit: () => void;
  submitting: boolean;
  effort: Effort | null;
  onEffortChange: (v: Effort | null) => void;
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
  const [pickerOpen, setPickerOpen] = useState(false);
  const insertPrompt = (text: string) => setPrompt(appendPrompt(prompt, text));

  return (
    <div className="responsive-split" style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16 }}>
      {/* LEFT — submit form */}
      <div className="card">
        <p style={{ margin: "0 0 18px", fontSize: 13, color: "var(--muted)" }}>
          This task inherits the container's current configuration at submission.{" "}
          <Link to={`/containers/${cid}/config`} style={{ color: "var(--ink)" }}>View config →</Link>
        </p>

        {/* Prompt label row with optional pre-fill tag + clear */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }} htmlFor="prompt">
            Prompt
          </label>
          {prefillId && (
            <Tag style={{ background: "var(--p-100)", borderColor: "var(--p-300)", color: "var(--ink)" }}>
              <Icons.Sparkles w={11} /> pre-filled from {prefillId}
            </Tag>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginLeft: "auto", gap: 6 }}
            onClick={() => setPickerOpen(true)}
          >
            <Icons.Prompt w={13} /> Use prompt
          </button>
          {prefillId && (
            <button className="btn btn-ghost btn-sm" onClick={onClear}>
              Clear
            </button>
          )}
        </div>

        <Textarea
          id="prompt"
          aria-label="Prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          style={{ minHeight: 120, fontFamily: "var(--font-mono)", fontSize: 13, lineHeight: 1.6 }}
        />

        {/* Output contract */}
        <OutputContractField
          type={outputType}
          onTypeChange={setOutputType}
          schemaText={schemaText}
          onSchemaTextChange={setSchemaText}
          structuredSupported={structuredSupported}
          driver={config.driver}
        />

        {/* Limits — per-task overrides. Blank inherits the container/tenant default. */}
        <div style={{ marginTop: 18 }}>
          <TaskLimitsFields
            supportsMaxIterations={supportsMaxIterations}
            iterDefault={iterDefault}
            tokensDefault={tokensDefault}
            timeoutDefault={timeoutDefault}
            tenantLimits={tenantLimits}
            maxIter={maxIter}
            setMaxIter={setMaxIter}
            maxTokens={maxTokens}
            setMaxTokens={setMaxTokens}
            timeoutS={timeoutS}
            setTimeoutS={setTimeoutS}
          />
        </div>

        {/* Effort — per-task override, same control as the chat Options panel. */}
        <div style={{ marginTop: 18 }}>
          <EffortField driver={config.driver} value={effort} onChange={onEffortChange} />
        </div>

        {/* Submit */}
        <div style={{ marginTop: 22, display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button variant="primary" style={{ gap: 6 }} onClick={onSubmit} disabled={!prompt || schemaBlocksSubmit || submitting}>
            <Icons.Send w={14} /> Submit task
          </Button>
        </div>
      </div>

      {/* RIGHT — inherited config + recent prompts */}
      <div className="flex-col" style={{ gap: 12, display: "flex", flexDirection: "column" }}>
        <div className="card">
          <h3 style={{ margin: "0 0 12px", fontSize: 13 }}>Inherits config from container</h3>
          <dl className="kv" style={{ fontSize: 12.5, gridTemplateColumns: "100px 1fr" }}>
            <dt>Driver</dt>
            <dd className="mono">{config.driver}</dd>
            <dt>Model</dt>
            <dd className="mono">{config.model}</dd>
            {EFFORT_DRIVERS.includes(config.driver) && (
              <>
                <dt>Effort</dt>
                <dd className="mono">{config.effort ?? "default"}</dd>
              </>
            )}
            <dt>Tools</dt>
            <dd style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {config.tools.slice(0, 6).map((t) => (
                <span key={t} className="tag" style={{ fontSize: 10 }}>
                  {t.replace("_", "")}
                </span>
              ))}
              {config.tools.length === 0 && <span style={{ fontSize: 12, color: "var(--muted)" }}>none</span>}
            </dd>
            <dt>Variant</dt>
            <dd>
              <span className="tag">{imageVariant}</span>
            </dd>
          </dl>
          <Link to={`/containers/${cid}/config`} style={{ fontSize: 12, marginTop: 8, display: "inline-block", color: "var(--ink)" }}>
            Edit configuration →
          </Link>
        </div>

        {recentTasks.length > 0 && (
          <div className="card">
            <h3 style={{ margin: "0 0 10px", fontSize: 13 }}>Recent prompts on this container</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {recentTasks.slice(0, 5).map((t) => (
                <Link
                  key={t.task_id}
                  to={`/containers/${cid}/tasks/${t.task_id}`}
                  data-task-id={t.task_id}
                  style={{ padding: 8, border: "1px solid var(--border)", borderRadius: 6, cursor: "pointer", display: "block", color: "inherit" }}
                >
                  <div className="clamp-2" style={{ fontSize: 12.5 }} title={t.prompt}>
                    {t.prompt}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4 }}>
                    <span className="id" style={{ fontSize: 11 }}>view task →</span>
                    <button
                      type="button"
                      className="mini-btn"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onPickRecent(t.prompt, t.task_id); }}
                    >
                      ↻ re-use prompt
                    </button>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
      <PromptPicker open={pickerOpen} onInsert={insertPrompt} onClose={() => setPickerOpen(false)} />
    </div>
  );
}
