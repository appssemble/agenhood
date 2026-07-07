import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button, Textarea } from "../ui";
import { Icons } from "../ui/Icon";
import { PromptPicker } from "../ui/PromptPicker";
import { appendPrompt } from "../lib/prompt";
import { ChatTurn } from "../components/ChatTurn";
import { OutputContractField } from "../components/OutputContractField";
import { TaskLimitsFields } from "../components/TaskLimitsFields";
import type { AgentConfig, OutputType, TaskStatus, TaskSummary, TenantLimits } from "../api/types";

type Turn = { taskId: string; prompt: string; status: TaskStatus; sessionId: string | null };

// Inline chat layout for submitting tasks: a scrolling thread of this session's
// turns plus a sticky composer. Shares prompt/output/limit state with the form
// layout via props so switching layouts preserves the draft.
export function SubmitTaskChat({
  cid,
  config,
  recentTasks,
  sessionId,
  submit,
  buildPayload,
  prompt,
  setPrompt,
  outputType,
  setOutputType,
  schemaText,
  setSchemaText,
  structuredSupported,
  schemaBlocksSubmit,
  onError,
  // limits
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
  recentTasks: TaskSummary[];
  // The currently selected session (from SessionPicker); null means "no
  // session" — the thread then shows only tasks that also have no session,
  // not every task in the container.
  sessionId: string | null;
  submit: { mutateAsync: (body: unknown) => Promise<{ task_id: string; status: string }>; isPending: boolean };
  buildPayload: (prompt: string) => unknown;
  prompt: string;
  setPrompt: (v: string) => void;
  outputType: OutputType;
  setOutputType: (v: OutputType) => void;
  schemaText: string;
  setSchemaText: (v: string) => void;
  structuredSupported: boolean;
  schemaBlocksSubmit: boolean;
  onError: (err: unknown) => void;
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
  // Locally-submitted turns, shown immediately for snappy feedback until the
  // task list refetch picks them up.
  const [pending, setPending] = useState<Turn[]>([]);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  // Insert a saved prompt: replace the draft when empty, else append after a blank line.
  const insertPrompt = (text: string) => setPrompt(appendPrompt(prompt, text));
  const threadRef = useRef<HTMLDivElement>(null);
  // Stick to the bottom until the user scrolls away. Starts true so entering the
  // chat view — and content streaming/loading in afterwards — always lands on
  // the latest turn.
  const pinned = useRef(true);

  // Scoped to the selected session (null ⇒ only tasks that also have no
  // session — not every task in the container), shown oldest→newest, then
  // pending sends for the same session not yet reflected in the history,
  // deduped by task id.
  const turns = useMemo<Turn[]>(() => {
    const scoped = recentTasks.filter((t) => (sessionId ? t.session_id === sessionId : !t.session_id));
    const history = scoped
      .slice()
      .reverse()
      .map((t) => ({ taskId: t.task_id, prompt: t.prompt, status: t.status, sessionId: t.session_id ?? null }));
    const seen = new Set(history.map((t) => t.taskId));
    const pendingScoped = pending.filter((p) => !seen.has(p.taskId) && p.sessionId === sessionId);
    return [...history, ...pendingScoped];
  }, [recentTasks, pending, sessionId]);

  // While pinned, glue the thread to the latest turn. Set immediately (pre-paint
  // when called from the layout effect → no top→bottom flash) and again next
  // frame to catch async transcript/stream content settling in afterwards.
  function stickToBottom() {
    const el = threadRef.current;
    if (!el || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => { if (el && pinned.current) el.scrollTop = el.scrollHeight; });
  }

  // Land at the bottom on entry and whenever the turn list changes.
  useLayoutEffect(() => { stickToBottom(); }, [turns.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Release the pin when the user scrolls up (so we never yank the viewport
  // while they read back through history) and re-arm it at the bottom.
  function onThreadScroll() {
    const el = threadRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function send() {
    const text = prompt.trim();
    if (!text || schemaBlocksSubmit || submit.isPending) return;
    try {
      const res = await submit.mutateAsync(buildPayload(text));
      setPending((prev) => [...prev, { taskId: res.task_id, prompt: text, status: "running", sessionId }]);
      setPrompt("");
      pinned.current = true; // sending always jumps to the new turn
      stickToBottom();
    } catch (err) {
      onError(err);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="chat-view">
      <div className="chat-thread" ref={threadRef} onScroll={onThreadScroll}>
        {turns.length === 0 ? (
          <div className="chat-empty">
            <span className="ico"><Icons.Bot w={24} /></span>
            <span className="h">Start a conversation</span>
            <span>
              Send a task and the agent's response streams in here. Each task inherits this
              container's <span className="mono">{config.driver}</span> · <span className="mono">{config.model}</span> config.
            </span>
          </div>
        ) : (
          turns.map((t) => (
            <ChatTurn key={t.taskId} cid={cid} taskId={t.taskId} prompt={t.prompt} initialStatus={t.status} onContentChange={stickToBottom} />
          ))
        )}
      </div>

      <div className="chat-composer">
        {optionsOpen && (
          <div className="chat-options" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <OutputContractField
              type={outputType}
              onTypeChange={setOutputType}
              schemaText={schemaText}
              onSchemaTextChange={setSchemaText}
              structuredSupported={structuredSupported}
              driver={config.driver}
            />
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
        )}

        <div className="chat-input-row">
          <Textarea
            aria-label="Prompt"
            placeholder="Send a task…  (Enter to send, Shift+Enter for a new line)"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={onKeyDown}
            style={{ fontFamily: "var(--font-mono)", fontSize: 13, lineHeight: 1.6 }}
          />
          <button
            type="button"
            className="chat-prompt-btn"
            aria-label="Use a saved prompt"
            title="Use a saved prompt"
            onClick={() => setPickerOpen(true)}
          >
            <Icons.Prompt w={18} />
          </button>
          <Button variant="primary" size="md" onClick={() => void send()} disabled={!prompt.trim() || schemaBlocksSubmit || submit.isPending}>
            <Icons.Send /> {submit.isPending ? "Sending…" : "Send"}
          </Button>
        </div>

        <div className="chat-composer-foot">
          <button type="button" className={`chat-options-toggle${optionsOpen ? " open" : ""}`} onClick={() => setOptionsOpen((v) => !v)}>
            <span className="chev"><Icons.ArrowRight w={12} /></span>
            Options
            {outputType !== "text" && <span className="tag" style={{ fontSize: 10 }}>{outputType}</span>}
          </button>
          <span className="chat-hint">
            <Icons.Cube w={12} /> inherits {config.driver} · {config.model}
          </span>
        </div>
      </div>

      <PromptPicker open={pickerOpen} onInsert={insertPrompt} onClose={() => setPickerOpen(false)} />
    </div>
  );
}
