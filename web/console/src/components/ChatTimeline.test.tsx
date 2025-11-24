import { describe, it, expect } from "vitest";
import { buildItems } from "./ChatTimeline";
import type { Event } from "../api/types";

/** Thin helper — casts type so tests stay terse without fighting the union. */
function evt(seq: number, type: string, payload: Record<string, unknown>): Event {
  return { seq, type: type as Event["type"], ts: "2026-06-30T00:00:00Z", payload };
}

// ─── core event-type dispatch ──────────────────────────────────────────────

describe("buildItems — core event types", () => {
  it("extracts text from assistant_message content blocks (text-only, skips others)", () => {
    const events: Event[] = [
      evt(1, "assistant_message", {
        content: [
          { type: "text", text: "Hello world" },
          { type: "tool_use" }, // non-text block — must be ignored
          { type: "text", text: "Second line" },
        ],
      }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "message", text: "Hello world\nSecond line" });
  });

  it("skips assistant_message with no text-type blocks", () => {
    const events: Event[] = [
      evt(1, "assistant_message", { content: [{ type: "tool_use" }] }),
    ];
    expect(buildItems(events)).toHaveLength(0);
  });

  it("pairs tool_call with tool_result via tool_use_id (ok / durationMs / output / args)", () => {
    const events: Event[] = [
      evt(1, "tool_result", { tool_use_id: "u1", ok: true, duration_ms: 42, content: "great" }),
      evt(2, "tool_call", { name: "bash", input: { command: "ls" }, tool_use_id: "u1" }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(1); // tool_result must be folded, not emitted separately
    const item = items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") {
      expect(item.name).toBe("bash");
      expect(item.ok).toBe(true);
      expect(item.durationMs).toBe(42);
      expect(item.output).toBe("great");
      expect(item.args).toBe("ls"); // single-key object → scalar value only
    }
  });

  it("tool_call without matching result has ok=undefined", () => {
    const events: Event[] = [
      evt(1, "tool_call", { name: "read", input: { path: "/foo.ts", needle: "bar" }, tool_use_id: "nope" }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(1);
    const item = items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") {
      expect(item.ok).toBeUndefined();
      expect(item.args).toContain("·"); // two-key object → "key: val · key: val"
    }
  });

  it("skips tool_result and token_update events (no emitted items)", () => {
    const events: Event[] = [
      evt(1, "tool_result", { tool_use_id: "u1", ok: true }),
      evt(2, "token_update", { tokens_in: 10, tokens_out: 5 }),
    ];
    expect(buildItems(events)).toHaveLength(0);
  });

  it("task_started → meta item containing driver and model", () => {
    const events: Event[] = [
      evt(1, "task_started", { driver: "claude-code", model: "claude-opus-4-5" }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(1);
    const item = items[0];
    expect(item.kind).toBe("meta");
    if (item.kind === "meta") {
      expect(item.label).toContain("claude-code");
      expect(item.label).toContain("claude-opus-4-5");
    }
  });

  it("status_change with terminal status → failed=true", () => {
    for (const to of ["failed", "timed_out", "cancelled"]) {
      const items = buildItems([evt(1, "status_change", { from: "running", to })]);
      expect(items[0]).toMatchObject({ kind: "status", from: "running", to, failed: true });
    }
  });

  it("status_change with non-terminal status → failed=false", () => {
    const items = buildItems([evt(1, "status_change", { from: "pending", to: "running" })]);
    expect(items[0]).toMatchObject({ kind: "status", to: "running", failed: false });
  });

  it("git ok with sha → ref truncated to 7 chars", () => {
    const items = buildItems([evt(1, "git", { op: "commit", ok: true, sha: "abcdef1234567890" })]);
    expect(items[0]).toMatchObject({ kind: "git", op: "commit", ok: true, ref: "abcdef1" });
  });

  it("git not ok → ref from error string", () => {
    const items = buildItems([evt(1, "git", { op: "push", ok: false, error: "auth failed" })]);
    expect(items[0]).toMatchObject({ kind: "git", ok: false, ref: "auth failed" });
  });

  it("file_changed → file item with op and path", () => {
    const items = buildItems([evt(1, "file_changed", { operation: "create", path: "src/hello.ts" })]);
    expect(items[0]).toMatchObject({ kind: "file", op: "create", path: "src/hello.ts" });
  });

  it("log → log item with level and message", () => {
    const items = buildItems([evt(1, "log", { level: "warn", message: "rate limit hit" })]);
    expect(items[0]).toMatchObject({ kind: "log", level: "warn", message: "rate limit hit" });
  });

  it("iteration_started → divider with step number", () => {
    const items = buildItems([evt(1, "iteration_started", { iteration: 3 })]);
    expect(items[0]).toMatchObject({ kind: "divider", label: "Step 3" });
  });

  it("opencode_stdout, codex_stdout, claude_stdout → stdout items", () => {
    const events: Event[] = [
      evt(1, "opencode_stdout", { line: "line from opencode" }),
      evt(2, "codex_stdout", { line: "line from codex" }),
      evt(3, "claude_stdout", { line: "line from claude" }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ kind: "stdout", line: "line from opencode" });
    expect(items[1]).toMatchObject({ kind: "stdout", line: "line from codex" });
    expect(items[2]).toMatchObject({ kind: "stdout", line: "line from claude" });
  });

  it("stdout skips empty or whitespace-only lines", () => {
    const events: Event[] = [
      evt(1, "opencode_stdout", { line: "" }),
      evt(2, "opencode_stdout", { line: "  " }),
    ];
    expect(buildItems(events)).toHaveLength(0);
  });
});

// ─── fileEdit / parsePatch / diffRows (via tool_call) ──────────────────────

const APPLY_PATCH = `*** Begin Patch
*** Update File: src/foo.ts
@@ context header
-old line
+new line
*** End Patch`;

describe("buildItems — parsePatch (apply_patch string input)", () => {
  it("string input containing a patch → tool item with edit FileDiff", () => {
    const items = buildItems([evt(1, "tool_call", { name: "apply_patch", input: APPLY_PATCH })]);
    expect(items).toHaveLength(1);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toBeDefined();
      expect(item.edit).toHaveLength(1);
      expect(item.edit![0].path).toBe("src/foo.ts");
      const types = item.edit![0].rows.map((r) => r.type);
      expect(types).toContain("del");
      expect(types).toContain("add");
      expect(item.args).toBe("src/foo.ts"); // editLabel for single file
    }
  });

  it("patch in command field of object input → tool with edit", () => {
    const items = buildItems([evt(1, "tool_call", { name: "shell", input: { command: APPLY_PATCH } })]);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toBeDefined();
      expect(item.name).toBe("shell");
    }
  });

  it("non-patch string input → no edit (parsePatch returns null)", () => {
    const items = buildItems([evt(1, "tool_call", { name: "bash", input: "echo hello" })]);
    const item = items[0];
    if (item.kind === "tool") expect(item.edit).toBeUndefined();
  });

  it("multi-file patch → edit with multiple FileDiff entries; args = '2 files'", () => {
    const multiPatch = `*** Begin Patch
*** Add File: a.ts
+new content
*** Update File: b.ts
-old
+new
*** End Patch`;
    const items = buildItems([evt(1, "tool_call", { name: "apply_patch", input: multiPatch })]);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toHaveLength(2);
      expect(item.args).toBe("2 files");
    }
  });
});

describe("buildItems — diffRows (old_string / new_string edit)", () => {
  it("old_string/new_string → edit with del + add rows (common head/tail trimmed)", () => {
    const items = buildItems([
      evt(1, "tool_call", {
        name: "edit",
        input: {
          path: "src/bar.ts",
          old_string: "line A\nremove me\nline C",
          new_string: "line A\nadded here\nline C",
        },
      }),
    ]);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toBeDefined();
      expect(item.edit![0].path).toBe("src/bar.ts");
      const rows = item.edit![0].rows;
      const del = rows.filter((r) => r.type === "del");
      const add = rows.filter((r) => r.type === "add");
      expect(del[0].text).toBe("remove me");
      expect(add[0].text).toBe("added here");
      // unchanged lines are preserved as ctx
      const ctx = rows.filter((r) => r.type === "ctx");
      expect(ctx.some((r) => r.text === "line A")).toBe(true);
      expect(ctx.some((r) => r.text === "line C")).toBe(true);
    }
  });

  it("camelCase oldString/newString → also produces edit", () => {
    const items = buildItems([
      evt(1, "tool_call", {
        name: "Edit",
        input: { file_path: "src/x.ts", oldString: "before", newString: "after" },
      }),
    ]);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toBeDefined();
      const rows = item.edit![0].rows;
      expect(rows.some((r) => r.type === "del" && r.text === "before")).toBe(true);
      expect(rows.some((r) => r.type === "add" && r.text === "after")).toBe(true);
    }
  });
});

describe("buildItems — write/create with content → add rows", () => {
  it("write_file with content → all add-type rows, one per content line", () => {
    const items = buildItems([
      evt(1, "tool_call", {
        name: "write_file",
        input: { path: "src/new.ts", content: "line1\nline2\nline3" },
      }),
    ]);
    const item = items[0];
    if (item.kind === "tool") {
      expect(item.edit).toBeDefined();
      const rows = item.edit![0].rows;
      expect(rows).toHaveLength(3);
      expect(rows.every((r) => r.type === "add")).toBe(true);
    }
  });
});

// ─── formatArgs (via tool_call input shapes) ───────────────────────────────

describe("buildItems — formatArgs branches", () => {
  it("null input → empty args string", () => {
    const item = buildItems([evt(1, "tool_call", { name: "noop", input: null })])[0];
    if (item.kind === "tool") expect(item.args).toBe("");
  });

  it("object with all-null values → empty args string", () => {
    const item = buildItems([evt(1, "tool_call", { name: "noop", input: { key: null } })])[0];
    if (item.kind === "tool") expect(item.args).toBe("");
  });

  it("object with multiple non-null entries → 'key: val · key: val' format", () => {
    const item = buildItems([
      evt(1, "tool_call", { name: "search", input: { query: "hello", limit: 10 } }),
    ])[0];
    if (item.kind === "tool") {
      expect(item.args).toContain("query: hello");
      expect(item.args).toContain("·");
    }
  });

  it("array value → '[N]' in scalar output", () => {
    const item = buildItems([
      evt(1, "tool_call", { name: "foo", input: { items: [1, 2, 3] } }),
    ])[0];
    if (item.kind === "tool") {
      expect(item.args).toContain("[3]");
    }
  });
});

// ─── fromRaw normalization (via opencode_event / codex_event default branch) ─

describe("buildItems — fromRaw: standard driver events", () => {
  it("type='text' with text field → message item", () => {
    const items = buildItems([
      evt(1, "opencode_event", { raw: { type: "text", text: "Hello from opencode" } }),
    ]);
    expect(items[0]).toMatchObject({ kind: "message", text: "Hello from opencode" });
  });

  it("type='assistant' with part.text → message item", () => {
    const items = buildItems([
      evt(1, "opencode_event", { raw: { type: "assistant", part: { text: "assistant reply" } } }),
    ]);
    expect(items[0]).toMatchObject({ kind: "message", text: "assistant reply" });
  });

  it("type='reasoning' with text field → message item", () => {
    const items = buildItems([
      evt(1, "opencode_event", { raw: { type: "reasoning", text: "thinking…" } }),
    ]);
    expect(items[0]).toMatchObject({ kind: "message", text: "thinking…" });
  });

  it("type contains 'tool' → tool item with name", () => {
    const items = buildItems([
      evt(1, "opencode_event", {
        raw: { type: "tool", part: { tool: "read_file", input: { path: "src/x.ts" } } },
      }),
    ]);
    const item = items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") expect(item.name).toBe("read_file");
  });

  it("type='error' → log item at error level", () => {
    const items = buildItems([
      evt(1, "opencode_event", { raw: { type: "error", error: { name: "NetworkError" } } }),
    ]);
    expect(items[0]).toMatchObject({ kind: "log", level: "error" });
  });

  it("type='step_start' (underscore) → divider", () => {
    const items = buildItems([evt(1, "codex_event", { raw: { type: "step_start" } })]);
    expect(items[0]).toMatchObject({ kind: "divider", label: "Step" });
  });

  it("type='step-start' (hyphen) → divider", () => {
    const items = buildItems([evt(1, "codex_event", { raw: { type: "step-start" } })]);
    expect(items[0]).toMatchObject({ kind: "divider", label: "Step" });
  });

  it("type='step.start' (dot) → divider", () => {
    const items = buildItems([evt(1, "codex_event", { raw: { type: "step.start" } })]);
    expect(items[0]).toMatchObject({ kind: "divider", label: "Step" });
  });

  it("finish / usage / token types → skipped (no emitted item)", () => {
    const events: Event[] = [
      evt(1, "opencode_event", { raw: { type: "usage" } }),
      evt(2, "opencode_event", { raw: { type: "finish" } }),
      evt(3, "opencode_event", { raw: { type: "token_usage" } }),
    ];
    expect(buildItems(events)).toHaveLength(0);
  });

  it("unknown type → event label item", () => {
    const items = buildItems([evt(1, "codex_event", { raw: { type: "some_custom_event" } })]);
    expect(items[0]).toMatchObject({ kind: "event", label: "some_custom_event" });
  });

  it("empty-type object → skipped", () => {
    const items = buildItems([evt(1, "codex_event", { raw: {} })]);
    expect(items).toHaveLength(0);
  });

  it("scalar string raw → event label item", () => {
    // p.raw is a string → fromRaw("plain string") → scalar branch → event label
    const items = buildItems([evt(1, "codex_event", { raw: "plain string" })]);
    expect(items[0]).toMatchObject({ kind: "event", label: "plain string" });
  });

  it("null raw (p.raw falsy → p used as fallback) → skipped when payload has no type", () => {
    const items = buildItems([evt(1, "codex_event", { raw: null })]);
    expect(items).toHaveLength(0);
  });
});

// ─── fromRaw: codex item.started / item.completed branch ───────────────────

describe("buildItems — fromRaw: codex thread items", () => {
  it("item.started → skipped; item.completed/agent_message → message", () => {
    const events: Event[] = [
      evt(1, "codex_event", {
        raw: { type: "item.started", item: { type: "agent_message", text: "should be ignored" } },
      }),
      evt(2, "codex_event", {
        raw: { type: "item.completed", item: { type: "agent_message", text: "done message" } },
      }),
    ];
    const items = buildItems(events);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "message", text: "done message" });
  });

  it("item.completed/reasoning → message", () => {
    const items = buildItems([
      evt(1, "codex_event", {
        raw: { type: "item.completed", item: { type: "reasoning", text: "let me think" } },
      }),
    ]);
    expect(items[0]).toMatchObject({ kind: "message", text: "let me think" });
  });

  it("item.completed/local_shell_call with apply_patch command → tool with edit, ok=true", () => {
    const PATCH = "*** Begin Patch\n*** Add File: x.ts\n+hello\n*** End Patch";
    const items = buildItems([
      evt(1, "codex_event", {
        raw: {
          type: "item.completed",
          item: { type: "local_shell_call", command: PATCH, exit_code: 0 },
        },
      }),
    ]);
    const item = items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") {
      expect(item.name).toBe("apply_patch");
      expect(item.ok).toBe(true);
      expect(item.edit).toBeDefined();
    }
  });

  it("item.completed/command_execution without patch → shell tool with output", () => {
    const items = buildItems([
      evt(1, "codex_event", {
        raw: {
          type: "item.completed",
          item: {
            type: "command_execution",
            command: "ls -la",
            exit_code: 0,
            aggregated_output: "file.ts",
          },
        },
      }),
    ]);
    const item = items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") {
      expect(item.name).toBe("shell");
      expect(item.ok).toBe(true);
      expect(item.output).toBe("file.ts");
    }
  });

  it("item.completed/command_execution with non-zero exit_code → ok=false", () => {
    const items = buildItems([
      evt(1, "codex_event", {
        raw: {
          type: "item.completed",
          item: { type: "command_execution", command: "failing-cmd", exit_code: 1 },
        },
      }),
    ]);
    const item = items[0];
    if (item.kind === "tool") expect(item.ok).toBe(false);
  });

  it("item.completed/error → log item", () => {
    const items = buildItems([
      evt(1, "codex_event", {
        raw: { type: "item.completed", item: { type: "error", message: "Something broke" } },
      }),
    ]);
    expect(items[0]).toMatchObject({ kind: "log", level: "error" });
  });

  it("item.completed/file_change (other itype) → skipped", () => {
    const items = buildItems([
      evt(1, "codex_event", {
        raw: { type: "item.completed", item: { type: "file_change" } },
      }),
    ]);
    expect(items).toHaveLength(0);
  });
});
