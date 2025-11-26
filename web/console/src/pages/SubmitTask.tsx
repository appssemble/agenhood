import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useContainer, useTemplates, useSubmitTask, useTasks } from "../api/queries";
import { useAuth } from "../auth/useAuth";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import type { OutputType } from "../api/types";
import { Icons } from "../ui/Icon";
import { parseSchema } from "../components/OutputContractField";
import { SubmitTaskForm } from "./SubmitTaskForm";
import { SubmitTaskChat } from "./SubmitTaskChat";

type Layout = "form" | "chat";
const LAYOUT_KEY = "agenhood.submitLayout";

export default function SubmitTask() {
  const { cid } = useParams<{ cid: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const containerQ = useContainer(cid!);
  const templatesQ = useTemplates();
  const submit = useSubmitTask(cid!);
  const tasksQ = useTasks(cid!);
  const { user } = useAuth();

  const [layout, setLayout] = useState<Layout>(() => {
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem(LAYOUT_KEY) : null;
    return saved === "chat" ? "chat" : "form";
  });
  useEffect(() => {
    try { localStorage.setItem(LAYOUT_KEY, layout); } catch { /* ignore */ }
  }, [layout]);

  const [prompt, setPrompt] = useState("");
  const [outputType, setOutputType] = useState<OutputType>("text");
  const [schemaText, setSchemaText] = useState("");
  const [prefillId, setPrefillId] = useState<string | null>(null);
  const [prefillDismissed, setPrefillDismissed] = useState(false);
  // Per-task limit overrides. null ⇒ inherit the container/tenant default.
  const [maxIter, setMaxIter] = useState<number | null>(null);
  const [maxTokens, setMaxTokens] = useState<number | null>(null);
  const [timeoutS, setTimeoutS] = useState<number | null>(null);

  const recentTask = tasksQ.data?.tasks?.[0] ?? null;

  // Pre-fill from the most recent task — form layout only, to keep the chat
  // composer empty for a fresh conversation.
  useEffect(() => {
    if (layout === "form" && !prefillDismissed && prompt === "" && recentTask) {
      setPrompt(recentTask.prompt);
      setPrefillId(recentTask.task_id);
    }
  }, [recentTask, prefillDismissed, layout]); // eslint-disable-line react-hooks/exhaustive-deps

  const config = containerQ.data?.config;
  const driverMeta = useMemo(
    () => templatesQ.data?.templates.find((t) => t.is_builtin && t.driver === config?.driver),
    [templatesQ.data, config?.driver]
  );
  const structuredSupported = driverMeta?.capabilities.supports_structured_output ?? true;
  const schema = useMemo(() => parseSchema(schemaText), [schemaText]);
  const schemaBlocksSubmit = outputType === "structured" && schemaText.trim() !== "" && !schema.ok;

  if (!config) return <div className="p-8 text-sm text-muted">Loading…</div>;

  // Limits inherit the container override, else the tenant default; max iterations
  // only applies to the vanilla driver (others manage their own loop).
  const tenantLimits = user?.tenant?.limits;
  const supportsMaxIterations = config.driver === "vanilla";
  const iterDefault = config.max_iterations ?? tenantLimits?.default_max_iterations;
  const tokensDefault = config.max_tokens ?? tenantLimits?.default_max_tokens;
  const timeoutDefault = config.timeout_seconds ?? tenantLimits?.default_task_timeout_seconds;

  function buildPayload(text: string) {
    const output =
      outputType === "structured" && schema.ok && schema.value
        ? { type: "structured" as const, schema: schema.value }
        : { type: outputType };
    return {
      prompt: text,
      output,
      limits: { max_iterations: maxIter, max_tokens: maxTokens, timeout_seconds: timeoutS },
      metadata: {},
    };
  }

  async function onSubmitForm() {
    try {
      const res = await submit.mutateAsync(buildPayload(prompt));
      navigate(`/containers/${cid}/tasks/${res.task_id}`);
    } catch (err) {
      toast.error("Couldn't submit task", err instanceof ApiError ? err.message : undefined);
    }
  }

  function onSubmitError(err: unknown) {
    toast.error("Couldn't submit task", err instanceof ApiError ? err.message : undefined);
  }

  function handleClear() {
    setPrompt("");
    setPrefillId(null);
    setPrefillDismissed(true);
  }

  function handlePickRecent(p: string, taskId: string) {
    setPrompt(p);
    setPrefillId(taskId);
    setPrefillDismissed(false);
  }

  const limitProps = {
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
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, overflow: "hidden" }}>
      <div className="submit-header">
        <div className="submit-header-card">
          <span className="submit-header-ico" aria-hidden="true"><Icons.Send w={19} /></span>
          <div className="submit-header-titles">
            <div className="t">Submit a task</div>
            <div className="sub">{layout === "chat" ? "Chat with the agent. Responses stream inline." : "Configure and submit a one-off task."}</div>
          </div>
          <div className="layout-switch" aria-label="Layout">
            <button type="button" aria-pressed={layout === "form"} className={layout === "form" ? "active" : ""} onClick={() => setLayout("form")}>
              <Icons.Checklist /> Form
            </button>
            <button type="button" aria-pressed={layout === "chat"} className={layout === "chat" ? "active" : ""} onClick={() => setLayout("chat")}>
              <Icons.Bot /> Chat
            </button>
          </div>
        </div>
      </div>

      {layout === "form" ? (
        <div className="submit-scroll">
          <div>
            <SubmitTaskForm
              cid={cid!}
              config={config}
              imageVariant={containerQ.data?.image_variant ?? "full"}
              recentTasks={tasksQ.data?.tasks ?? []}
              prompt={prompt}
              setPrompt={setPrompt}
              prefillId={prefillId}
              onClear={handleClear}
              onPickRecent={handlePickRecent}
              outputType={outputType}
              setOutputType={setOutputType}
              schemaText={schemaText}
              setSchemaText={setSchemaText}
              structuredSupported={structuredSupported}
              schemaBlocksSubmit={schemaBlocksSubmit}
              onSubmit={onSubmitForm}
              submitting={submit.isPending}
              {...limitProps}
            />
          </div>
        </div>
      ) : (
        <SubmitTaskChat
          cid={cid!}
          config={config}
          recentTasks={tasksQ.data?.tasks ?? []}
          submit={submit}
          buildPayload={buildPayload}
          prompt={prompt}
          setPrompt={setPrompt}
          outputType={outputType}
          setOutputType={setOutputType}
          schemaText={schemaText}
          setSchemaText={setSchemaText}
          structuredSupported={structuredSupported}
          schemaBlocksSubmit={schemaBlocksSubmit}
          onError={onSubmitError}
          {...limitProps}
        />
      )}
    </div>
  );
}
