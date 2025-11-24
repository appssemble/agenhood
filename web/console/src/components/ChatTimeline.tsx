import { useState } from "react";
import { Icons } from "../ui/Icon";
import type { Event } from "../api/types";
import { containerFileRawUrl } from "../api/fileUrls";
function downloadHref(cid: string, path: string) {
  return containerFileRawUrl(cid, path);
}

/* ── value formatting ─────────────────────────────────────────── */
function scalar(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return `[${v.length}]`;
  return "{…}";
}
function clip(s: string, n = 200): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
// "value" for a single arg, else "key: value · key: value" — never raw JSON.
function formatArgs(input: unknown): string {
  if (input == null) return "";
  if (typeof input !== "object") return clip(scalar(input), 120);
  const entries = Object.entries(input as Record<string, unknown>).filter(([, v]) => v != null && v !== "");
  if (entries.length === 0) return "";
  if (entries.length === 1) return clip(scalar(entries[0][1]), 120);
  return entries.map(([k, v]) => `${k}: ${clip(scalar(v), 48)}`).join(" · ");
}
function asText(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

const strOf = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

// Parse an apply_patch envelope (`*** Begin Patch` … `*** End Patch`, as used by
// codex/apply_patch) into one FileDiff per touched file. Returns null if `text`
// isn't such a patch — also tolerates the patch sitting inside a heredoc/command.
function parsePatch(text: string): FileDiff[] | null {
  if (!text.includes("*** Begin Patch")) return null;
  const files: FileDiff[] = [];
  let cur: FileDiff | null = null;
  for (const line of text.split("\n")) {
    if (line.startsWith("*** End Patch")) break; // ignore any heredoc terminator after
    if (line.startsWith("*** Begin Patch")) continue;
    const m = line.match(/^\*\*\* (Add|Update|Delete) File: (.+)$/);
    if (m) { cur = { path: m[2].trim(), rows: [] }; files.push(cur); continue; }
    if (line.startsWith("*** ")) continue; // e.g. "*** Move to: …"
    if (!cur) continue;
    if (line.startsWith("@@")) {
      const ctx = line.slice(2).trim();
      if (ctx) cur.rows.push({ type: "ctx", text: ctx });
    } else if (line[0] === "+") cur.rows.push({ type: "add", text: line.slice(1) });
    else if (line[0] === "-") cur.rows.push({ type: "del", text: line.slice(1) });
    else cur.rows.push({ type: "ctx", text: line.startsWith(" ") ? line.slice(1) : line });
  }
  return files.length ? files : null;
}

// Extract a file mutation from a tool call's input so it can be shown as a diff.
// Keys off the input fields rather than the tool name so it works across drivers:
// an apply_patch envelope (string or `patch`/`diff`/`input`/`command` field), a
// before/after edit (old_string/new_string, snake or camel case), or a full write.
function fileEdit(name: string, input: unknown): FileDiff[] | undefined {
  if (typeof input === "string") return parsePatch(input) ?? undefined;
  if (!input || typeof input !== "object") return undefined;
  const p = input as Record<string, unknown>;
  for (const k of ["patchText", "patch", "diff", "input", "command"]) {
    const s = strOf(p[k]);
    if (s) { const f = parsePatch(s); if (f) return f; }
  }
  const path = strOf(p.path) ?? strOf(p.file_path) ?? strOf(p.filePath) ?? strOf(p.filename);
  const before = strOf(p.old_string) ?? strOf(p.oldString);
  const after = strOf(p.new_string) ?? strOf(p.newString);
  if (before != null && after != null) return [{ path, rows: diffRows(before, after) }];
  const content = strOf(p.content) ?? strOf(p.file_text) ?? strOf(p.contents);
  const n = name.toLowerCase();
  if (content != null && (n.includes("write") || n.includes("create")))
    return [{ path, rows: content.split("\n").map((text) => ({ type: "add", text } as DiffRow)) }];
  return undefined;
}

// The args-line label for an edit: the file path for a single file, else a count.
function editLabel(files: FileDiff[]): string {
  if (files.length === 1) return files[0].path ?? "";
  return `${files.length} files`;
}

// Line diff between before/after. Trims the common head/tail so unchanged
// context isn't shown wholesale, capping retained context to a few lines.
type DiffRow = { type: "ctx" | "del" | "add"; text: string };
function diffRows(before: string, after: string, ctx = 3): DiffRow[] {
  const a = before.split("\n");
  const b = after.split("\n");
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let ta = a.length;
  let tb = b.length;
  while (ta > head && tb > head && a[ta - 1] === b[tb - 1]) { ta--; tb--; }
  const rows: DiffRow[] = [];
  const headStart = Math.max(0, head - ctx);
  if (headStart > 0) rows.push({ type: "ctx", text: `… ${headStart} unchanged line${headStart > 1 ? "s" : ""}` });
  for (let i = headStart; i < head; i++) rows.push({ type: "ctx", text: a[i] });
  for (let i = head; i < ta; i++) rows.push({ type: "del", text: a[i] });
  for (let i = head; i < tb; i++) rows.push({ type: "add", text: b[i] });
  const tailEnd = Math.min(a.length, ta + ctx);
  for (let i = ta; i < tailEnd; i++) rows.push({ type: "ctx", text: a[i] });
  const trailing = a.length - tailEnd;
  if (trailing > 0) rows.push({ type: "ctx", text: `… ${trailing} unchanged line${trailing > 1 ? "s" : ""}` });
  return rows;
}

/* ── normalized timeline items ────────────────────────────────── */
// A single file's diff (pre-computed rows), extracted from an edit/write/patch
// tool's input. A tool call may touch several files (a multi-file patch).
type FileDiff = { path?: string; rows: DiffRow[] };

type Item =
  | { id: string; kind: "message"; text: string }
  | { id: string; kind: "tool"; name: string; args: string; ok?: boolean; durationMs?: number; output?: string; edit?: FileDiff[] }
  | { id: string; kind: "file"; op: string; path: string }
  | { id: string; kind: "git"; op: string; ok: boolean; ref?: string }
  | { id: string; kind: "log"; level: string; message: string }
  | { id: string; kind: "stdout"; line: string }
  | { id: string; kind: "status"; from: string; to: string; failed: boolean }
  | { id: string; kind: "meta"; label: string }
  | { id: string; kind: "divider"; label: string }
  | { id: string; kind: "result"; output: unknown }
  | { id: string; kind: "event"; label: string };

const TERMINAL_FAIL = new Set(["failed", "timed_out", "cancelled"]);

// Assistant narration carried by a driver event (opencode/codex), if any.
function rawText(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, any>;
  const type = String(r.type ?? r.event ?? r.kind ?? "").toLowerCase();
  if (!["text", "assistant", "message", "reasoning"].includes(type)) return null;
  const part = r.part && typeof r.part === "object" ? (r.part as Record<string, any>) : null;
  return asText(part?.text ?? r.text ?? r.message);
}

// Normalize a driver event's nested `raw` payload into a timeline item.
function fromRaw(id: string, raw: unknown): Item | null {
  if (!raw || typeof raw !== "object") {
    const s = scalar(raw);
    return s ? { id, kind: "event", label: clip(s, 80) } : null;
  }
  const r = raw as Record<string, any>;
  const part = r.part && typeof r.part === "object" ? (r.part as Record<string, any>) : null;
  const state = part?.state && typeof part.state === "object" ? (part.state as Record<string, any>) : null;
  const type = String(r.type ?? r.event ?? r.kind ?? "").toLowerCase();

  // Codex thread items (`item.completed`) wrap the real payload under `item`.
  const item = r.item && typeof r.item === "object" ? (r.item as Record<string, any>) : null;
  if (item && (type === "item.completed" || type === "item.started")) {
    if (type === "item.started") return null; // wait for the completed twin
    const itype = String(item.type ?? "").toLowerCase();
    if (itype === "agent_message" || itype === "reasoning") {
      const t = asText(item.text);
      return t ? { id, kind: "message", text: t } : null;
    }
    if (itype === "command_execution" || itype === "local_shell_call") {
      // apply_patch runs as a shell command; its patch text sits in `command`.
      const cmd = strOf(item.command) ?? "";
      const edit = fileEdit("apply_patch", cmd);
      const ok = typeof item.exit_code === "number" ? item.exit_code === 0
        : item.status ? item.status !== "failed" : undefined;
      return {
        id, kind: "tool", name: edit ? "apply_patch" : "shell",
        args: edit ? editLabel(edit) : clip(scalar(cmd), 80),
        ok,
        output: edit ? undefined : asText(item.aggregated_output) ?? undefined,
        edit,
      };
    }
    if (itype === "error") return { id, kind: "log", level: "error", message: clip(scalar(item.message ?? "error"), 240) };
    return null; // file_change etc. covered by the fs-watcher `file_changed` events
  }

  const text = rawText(raw);
  if (text != null) return { id, kind: "message", text };

  if (type.includes("tool")) {
    const name = String(part?.tool ?? part?.name ?? r.tool ?? r.name ?? "tool");
    const ok = typeof part?.ok === "boolean" ? part.ok
      : state?.status ? state.status === "completed" || state.status === "success"
      : typeof r.ok === "boolean" ? r.ok : undefined;
    const input = part?.input ?? part?.args ?? state?.input ?? r.input;
    const edit = fileEdit(name, input);
    return {
      id, kind: "tool", name,
      args: edit ? editLabel(edit) : formatArgs(input),
      ok,
      output: asText(state?.output ?? part?.output ?? state?.metadata?.output) ?? undefined,
      edit,
    };
  }
  if (type === "error") {
    const msg = r.error?.data?.message ?? r.error?.name ?? r.message ?? "error";
    return { id, kind: "log", level: "error", message: clip(scalar(msg), 240) };
  }
  if (type.startsWith("step-start") || type === "step_start" || type === "step.start") {
    return { id, kind: "divider", label: "Step" };
  }
  if (type.includes("finish") || type.includes("usage") || type.includes("token")) return null;
  return type ? { id, kind: "event", label: type } : null;
}

// Build the ordered item list. tool_call pairs with its tool_result by
// tool_use_id (the result carries ok / duration / output content).
export function buildItems(events: Event[]): Item[] {
  const results = new Map<string, Record<string, any>>();
  for (const e of events) {
    if (e.type === "tool_result") {
      const p = e.payload as Record<string, any>;
      if (p.tool_use_id) results.set(String(p.tool_use_id), p);
    }
  }

  const items: Item[] = [];
  for (const e of events) {
    const p = e.payload as Record<string, any>;
    const id = String(e.seq);
    switch (e.type) {
      case "assistant_message": {
        const text = ((p.content as Array<{ type: string; text?: string }> | undefined) ?? [])
          .filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
        if (text) items.push({ id, kind: "message", text });
        break;
      }
      case "tool_call": {
        const res = p.tool_use_id ? results.get(String(p.tool_use_id)) : undefined;
        const name = String(p.name ?? "tool");
        const edit = fileEdit(name, p.input);
        items.push({
          id, kind: "tool", name, args: edit ? editLabel(edit) : formatArgs(p.input),
          ok: typeof res?.ok === "boolean" ? res.ok : undefined,
          durationMs: typeof res?.duration_ms === "number" ? res.duration_ms : undefined,
          output: asText(res?.content) ?? undefined,
          edit,
        });
        break;
      }
      case "tool_result":
      case "token_update":
        break; // folded into tool_call / cumulative counter (shown in the footer)
      case "task_started":
        items.push({ id, kind: "meta", label: `Started · ${p.driver ?? "?"} · ${p.model ?? "?"}` });
        break;
      case "status_change":
        items.push({ id, kind: "status", from: String(p.from ?? ""), to: String(p.to ?? ""), failed: TERMINAL_FAIL.has(String(p.to)) });
        break;
      case "git": {
        const ok = p.ok !== false;
        items.push({ id, kind: "git", op: String(p.op ?? "git"), ok, ref: p.sha ? String(p.sha).slice(0, 7) : ok ? undefined : (p.error ? String(p.error) : undefined) });
        break;
      }
      case "file_changed":
        items.push({ id, kind: "file", op: String(p.operation ?? "modify"), path: String(p.path ?? "") });
        break;
      case "log":
        items.push({ id, kind: "log", level: String(p.level ?? "info"), message: String(p.message ?? "") });
        break;
      case "iteration_started":
        items.push({ id, kind: "divider", label: `Step ${p.iteration}` });
        break;
      case "opencode_stdout":
      case "codex_stdout":
      case "claude_stdout": {
        const line = asText(p.line);
        if (line) items.push({ id, kind: "stdout", line });
        break;
      }
      default: {
        const it = fromRaw(id, p.raw ?? p);
        if (it) items.push(it);
        break;
      }
    }
  }
  return items;
}

/* ── rendering ────────────────────────────────────────────────── */
const OP_LABEL: Record<string, string> = { create: "Created", modify: "Edited", delete: "Deleted" };
const GIT_LABEL: Record<string, string> = { commit: "Committed", push: "Pushed", pull: "Pulled", clone: "Cloned" };
function gitLabel(op: string, ok: boolean) {
  return ok ? (GIT_LABEL[op] ?? op) : `${op} failed`;
}

// Collapsible diff for an edit/write/patch tool. Renders one block per touched
// file (a multi-file patch shows a path header above each), with +/- rows.
const SIGN = { ctx: " ", add: "+", del: "-" } as const;
function DiffStep({ edit }: { edit: FileDiff[] }) {
  const total = edit.reduce((n, f) => n + f.rows.length, 0);
  const changes = edit.reduce((n, f) => n + f.rows.filter((r) => r.type !== "ctx").length, 0);
  const [open, setOpen] = useState(() => total <= 14);
  const multi = edit.length > 1;
  return (
    <>
      <button type="button" className={`ev-out-toggle${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)}>
        <span className="chev"><Icons.ArrowRight w={11} /></span>
        {open ? "Hide diff" : `Show diff · ${changes} line${changes === 1 ? "" : "s"}`}
      </button>
      {open && (
        <div className="ev-diff">
          {edit.map((f, fi) => (
            <div key={fi}>
              {multi && f.path && <div className="ev-diff-file">{f.path}</div>}
              {f.rows.map((r, i) => (
                <div key={i} className={`ev-diff-row ${r.type}`}>
                  <span className="sign">{SIGN[r.type]}</span>{r.text}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ToolStep({ item }: { item: Extract<Item, { kind: "tool" }> }) {
  const raw = item.output?.trim();
  // A terse "ok"/"done" output is already conveyed by the status chip. When the
  // call carried a file edit, the diff replaces the (just-a-confirmation) output.
  const out = !item.edit && raw && raw.length > 3 && !/^(ok|done|success|true|null)$/i.test(raw) ? raw : undefined;
  const [open, setOpen] = useState(() => !!out && out.length <= 220);
  const lines = out ? out.split("\n").length : 0;
  return (
    <div className={`ev-tool${item.ok === false ? " err" : ""}`}>
      <div className="ev-tool-head">
        <span className="ev-tool-ico"><Icons.Wrench /></span>
        <span className="ev-tool-name">{item.name}</span>
        {item.args && <span className="ev-tool-args">{item.args}</span>}
        {item.ok != null && (
          <span className={`ev-chip ${item.ok ? "ok" : "err"}`}>
            <span className="dot" />
            {item.ok ? "ok" : "error"}{item.durationMs != null ? ` · ${item.durationMs}ms` : ""}
          </span>
        )}
      </div>
      {item.edit && item.ok !== false && <DiffStep edit={item.edit} />}
      {out && (
        <>
          <button type="button" className={`ev-out-toggle${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)}>
            <span className="chev"><Icons.ArrowRight w={11} /></span>
            {open ? "Hide output" : `Show output${lines > 1 ? ` · ${lines} lines` : ""}`}
          </button>
          {open && <pre className="ev-out">{out}</pre>}
        </>
      )}
    </div>
  );
}

function ItemView({ item, cid }: { item: Item; cid: string }) {
  switch (item.kind) {
    case "message":
      return <div className="ev-msg">{item.text}</div>;
    case "tool":
      return <ToolStep item={item} />;
    case "file":
      return (
        <div className="ev-line">
          <Icons.File />
          <span className={`ev-op ${item.op}`}>{OP_LABEL[item.op] ?? item.op}</span>
          <a className="path" href={downloadHref(cid, item.path)}>{item.path.split("/").pop()}</a>
        </div>
      );
    case "git":
      return (
        <div className={`ev-line${item.ok ? "" : " err"}`}>
          <Icons.Code />
          <span className="ev-op">{gitLabel(item.op, item.ok)}</span>
          {item.ref && <span className="ev-ref">{item.ref}</span>}
        </div>
      );
    case "status":
      return (
        <div className={`ev-line mono${item.failed ? " err" : ""}`}>
          <Icons.Arrow />
          <span>{item.from} → {item.to}</span>
        </div>
      );
    case "meta":
      return <div className="ev-line mono"><Icons.Play /><span>{item.label}</span></div>;
    case "result":
      return (
        <div className="ev-result">
          <div className="ev-result-head"><Icons.Check /><span>Result</span></div>
          {typeof item.output === "string"
            ? <div className="ev-result-text">{item.output}</div>
            : <pre className="ev-result-json">{JSON.stringify(item.output, null, 2)}</pre>}
        </div>
      );
    case "log":
      return (
        <div className={`ev-line ${item.level === "error" ? "err" : item.level === "warn" ? "warn" : ""}`}>
          {item.level === "error" || item.level === "warn" ? <Icons.Warn /> : <Icons.Info />}
          <span>{item.message}</span>
        </div>
      );
    case "stdout":
      return <div className="ev-line mono"><Icons.Logs /><span>{item.line}</span></div>;
    case "divider":
      return <div className="ev-divider">{item.label}</div>;
    case "event":
      return <div className="ev-line mono"><Icons.Bolt /><span>{item.label}</span></div>;
  }
}

// Renders a task's events as an ordered, top-to-bottom transcript: assistant
// messages, tool steps (with their result + collapsible output), file changes,
// git ops, logs, terminal output, and step dividers. When `result` is provided
// it's appended as the final step (the answer); a trailing message that just
// duplicates it is dropped.
export function ChatTimeline({ cid, events, result }: { cid: string; events: Event[]; result?: unknown }) {
  let items = buildItems(events);

  const resultText = typeof result === "string" ? result.trim() : undefined;
  if (resultText) {
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it.kind === "message") {
        if (it.text.trim() === resultText) items = items.filter((_, idx) => idx !== i);
        break; // only the last message can be the final answer
      }
    }
  }
  if (result !== undefined && result !== null) {
    items = [...items, { id: "result", kind: "result", output: result }];
  }

  if (items.length === 0) return null;
  return (
    <div className="ev-list">
      {items.map((it) => <ItemView key={it.id} item={it} cid={cid} />)}
    </div>
  );
}
