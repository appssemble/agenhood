import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import type { Event } from "../api/types";
import SubmitTask from "./SubmitTask";

vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({ cid: "con_1" }),
  useNavigate: () => vi.fn(),
}));

// Drive the SSE stream synchronously: emit one assistant message + a terminal
// status_change, then hand back a no-op unsubscribe.
vi.mock("../api/events", () => ({
  subscribeEvents: (_cid: string, _tid: string, opts: { onOpen?: () => void; onEvent: (e: Event) => void }) => {
    opts.onOpen?.();
    opts.onEvent({ seq: 1, type: "tool_call", ts: "t", payload: { name: "web_search", input: { q: "Q3" } } });
    opts.onEvent({ seq: 2, type: "tool_result", ts: "t", payload: { ok: true, duration_ms: 30 } });
    opts.onEvent({ seq: 3, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: "Here is the summary." }] } });
    opts.onEvent({ seq: 4, type: "status_change", ts: "t", payload: { from: "running", to: "completed" } });
    return () => {};
  },
}));

const tpl = {
  id: "tpl_v", tenant_id: null, name: "Vanilla", driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] }, skills: [], limits: {}, is_builtin: true,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: [], tools_user_editable: true, supports_context: true }, available_tool_specs: [],
};

function setup() {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "member", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [tpl] })));
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({ id: "con_1", name: "c", external_id: null, status: "running", image_variant: "full", image_tag: "v",
    config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } }, metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
  server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [] })));
  server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({ sessions: [] })));
  server.use(http.get("/v1/containers/con_1/tasks/tsk_9", () => HttpResponse.json({
    task_id: "tsk_9", status: "completed", prompt: "Summarize the report", started_at: "t", ended_at: "t",
    tokens_in: 10, tokens_out: 20, iterations_used: 1, result: { output: "Summary text", files: [] }, error: null,
  })));
}

describe("SubmitTask chat layout", () => {
  beforeEach(() => { localStorage.clear(); });

  it("switches to chat, persists the choice, and streams a sent task", async () => {
    setup();
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ task_id: "tsk_9", status: "running", started_at: "t" });
    }));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);

    // Toggle to chat
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));
    expect(localStorage.getItem("agenhood.submitLayout")).toBe("chat");

    // Send a prompt (target the composer textarea by its exact label — the
    // "Use a saved prompt" button also matches a loose /Prompt/i).
    await userEvent.type(await screen.findByLabelText("Prompt"), "Summarize the report");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(body?.prompt).toBe("Summarize the report"));

    // User bubble + streamed intermediate step + assistant message render
    expect(await screen.findByText("Summarize the report")).toBeInTheDocument();
    expect(await screen.findByText("web_search")).toBeInTheDocument();
    expect(await screen.findByText("Here is the summary.")).toBeInTheDocument();
  });

  it("scrolls to the bottom on entering chat, even as transcripts load in", async () => {
    setup();
    server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [
      { task_id: "tsk_b", status: "completed", prompt: "Second prompt", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1 },
      { task_id: "tsk_a", status: "completed", prompt: "First prompt", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1 },
    ] })));
    server.use(http.get("/v1/containers/con_1/tasks/:tid", ({ params }) => HttpResponse.json({
      task_id: params.tid, status: "completed", prompt: "x", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1, result: null, error: null,
    })));
    server.use(http.get("/v1/containers/con_1/tasks/:tid/events", ({ params }) => HttpResponse.json({ events: [
      { seq: 1, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: params.tid === "tsk_b" ? "The second answer, long enough that the thread keeps growing as it loads" : "The first answer, also long enough to grow the thread height after the initial render" }] } },
    ] })));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));

    const thread = document.querySelector(".chat-thread") as HTMLElement;
    // jsdom has no layout — model scroll height by content so it grows as the
    // async transcripts render in (the real-world cause of the stuck scroll).
    Object.defineProperty(thread, "clientHeight", { configurable: true, get: () => 300 });
    Object.defineProperty(thread, "scrollHeight", { configurable: true, get: () => 100 + (thread.textContent?.length ?? 0) * 2 });

    await screen.findByText(/The first answer/);
    await screen.findByText(/The second answer/);

    // The thread is pinned to the very bottom once everything has settled.
    await waitFor(() => expect(thread.scrollHeight - thread.scrollTop - thread.clientHeight).toBeLessThanOrEqual(0));
  });

  it("seeds the thread with full container history and shows results by default", async () => {
    setup();
    server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [
      // newest-first from the API
      { task_id: "tsk_b", status: "completed", prompt: "Second prompt", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1 },
      { task_id: "tsk_a", status: "completed", prompt: "First prompt", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1 },
    ] })));
    // Finished turns fetch their detail (result fallback) + stored events.
    server.use(http.get("/v1/containers/con_1/tasks/:tid", ({ params }) => HttpResponse.json({
      task_id: params.tid, status: "completed", prompt: "x", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1, result: null, error: null,
    })));
    // Each finished turn replays its stored events (transcript + steps),
    // including a nested driver event that must render cleanly (no JSON).
    server.use(http.get("/v1/containers/con_1/tasks/:tid/events", ({ params }) => HttpResponse.json({ events: [
      { seq: 1, type: "tool_call", ts: "t", payload: { name: "read_file", input: { path: "a.txt" } } },
      { seq: 2, type: "tool_result", ts: "t", payload: { ok: true, duration_ms: 5 } },
      { seq: 3, type: "opencode_event", ts: "t", payload: { raw: { type: "tool", part: { tool: "grep", input: { pattern: "foo" } } } } },
      { seq: 4, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: params.tid === "tsk_b" ? "The second answer" : "The first answer" }] } },
    ] })));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));

    // Both historical prompts appear as user bubbles, oldest first.
    expect(await screen.findByText("First prompt", { selector: ".chat-bubble" })).toBeInTheDocument();
    expect(screen.getByText("Second prompt", { selector: ".chat-bubble" })).toBeInTheDocument();

    // The transcript (intermediate steps + final answer) renders inline by default.
    expect(await screen.findByText("The first answer")).toBeInTheDocument();
    expect(await screen.findByText("The second answer")).toBeInTheDocument();
    expect(screen.getAllByText("read_file").length).toBeGreaterThan(0);
    // The nested driver event renders as a clean tool step, not raw JSON.
    expect(screen.getAllByText("grep").length).toBeGreaterThan(0);
    expect(screen.getAllByText("foo").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\{"tool"|"part"|"input"/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /show result/i })).not.toBeInTheDocument();
  });

  it("sends the selected session_id with the task and filters the thread to it", async () => {
    setup();
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({
      sessions: [{ session_id: "sess-1", driver: "vanilla", task_count: 1,
        first_created_at: "t1", last_created_at: "t2", busy: false }],
    })));
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ task_id: "tsk_9", status: "running", started_at: "t", session_id: body.session_id });
    }));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));

    await userEvent.click(await screen.findByRole("button", { name: /no session/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /sess-1/ }));

    await userEvent.type(await screen.findByLabelText("Prompt"), "Continue our chat");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(body?.session_id).toBe("sess-1"));
  });

  it("scopes the visible thread to the selected session, excluding other tasks", async () => {
    setup();
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({
      sessions: [{ session_id: "sess-1", driver: "vanilla", task_count: 1,
        first_created_at: "t1", last_created_at: "t2", busy: false }],
    })));
    // A mix: one task in "sess-1", one in a different session, one with none.
    server.use(http.get("/v1/containers/con_1/tasks", ({ request }) => {
      const url = new URL(request.url);
      const filter = url.searchParams.get("session_id");
      const all = [
        { task_id: "tsk_in", status: "completed", prompt: "In session one", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1, session_id: "sess-1" },
        { task_id: "tsk_other", status: "completed", prompt: "In a different session", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1, session_id: "sess-2" },
        { task_id: "tsk_none", status: "completed", prompt: "One-off, no session", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1 },
      ];
      const tasks = filter ? all.filter((t) => t.session_id === filter) : all;
      return HttpResponse.json({ tasks });
    }));
    server.use(http.get("/v1/containers/con_1/tasks/:tid", ({ params }) => HttpResponse.json({
      task_id: params.tid, status: "completed", prompt: "x", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 2, iterations_used: 1, result: null, error: null,
    })));
    server.use(http.get("/v1/containers/con_1/tasks/:tid/events", () => HttpResponse.json({ events: [] })));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));

    // Default ("No session"): only the session-less task is visible — the API
    // isn't filtered client-side-only, so this also proves the "no session"
    // view excludes tasks that DO belong to a session, not just the reverse.
    expect(await screen.findByText("One-off, no session", { selector: ".chat-bubble" })).toBeInTheDocument();
    expect(screen.queryByText("In session one", { selector: ".chat-bubble" })).not.toBeInTheDocument();
    expect(screen.queryByText("In a different session", { selector: ".chat-bubble" })).not.toBeInTheDocument();

    // Switch to "sess-1": only that session's task is visible.
    await userEvent.click(await screen.findByRole("button", { name: /no session/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /sess-1/ }));

    expect(await screen.findByText("In session one", { selector: ".chat-bubble" })).toBeInTheDocument();
    expect(screen.queryByText("In a different session", { selector: ".chat-bubble" })).not.toBeInTheDocument();
    expect(screen.queryByText("One-off, no session", { selector: ".chat-bubble" })).not.toBeInTheDocument();
  });

  it("omits session_id when 'No session' is selected (default)", async () => {
    setup();
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({ sessions: [] })));
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ task_id: "tsk_9", status: "running", started_at: "t", session_id: null });
    }));

    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /chat/i }));
    await userEvent.type(await screen.findByLabelText("Prompt"), "One-off message");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body.session_id).toBeUndefined();
  });
});
