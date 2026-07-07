import { describe, it, expect, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { ChatTurn } from "./ChatTurn";
import { SessionPicker } from "./SessionPicker";
import { subscribeEvents } from "../api/events";

// Default: keep the streamed task RUNNING — emit one non-terminal event and
// never a terminal status_change, so the Stop affordance stays visible.
// Individual tests override this via mockImplementationOnce for a single call.
vi.mock("../api/events", () => ({
  subscribeEvents: vi.fn(
    (
      _cid: string,
      _tid: string,
      opts: { onOpen?: () => void; onEvent: (e: unknown) => void },
    ) => {
      opts.onOpen?.();
      opts.onEvent({ seq: 1, type: "tool_call", ts: "t", payload: { name: "bash", input: {} } });
      return () => {};
    },
  ),
}));

describe("ChatTurn — stop a running task", () => {
  it("shows Stop on a running turn and gracefully cancels it on click", async () => {
    server.use(http.get("/v1/containers/con_1/tasks/tsk_run", () => HttpResponse.json({
      task_id: "tsk_run", status: "running", prompt: "Refactor auth", started_at: "t", ended_at: null,
      tokens_in: 0, tokens_out: 0, iterations_used: 0, result: null, error: null })));
    let cancelled = false;
    server.use(http.post("/v1/containers/con_1/tasks/tsk_run/cancel", () => {
      cancelled = true;
      return HttpResponse.json({ task_id: "tsk_run", status: "cancelled" });
    }));

    renderWithProviders(
      <ChatTurn cid="con_1" taskId="tsk_run" prompt="Refactor auth" initialStatus="running" />,
    );

    const stop = await screen.findByRole("button", { name: /stop/i });
    await userEvent.click(stop);

    // Calls the graceful cancel endpoint…
    await waitFor(() => expect(cancelled).toBe(true));
    // …and reflects an optimistic "Stopping…" state.
    expect(await screen.findByText(/stopping/i)).toBeInTheDocument();
  });

  it("does not offer Stop on a finished turn", async () => {
    server.use(http.get("/v1/containers/con_1/tasks/tsk_done", () => HttpResponse.json({
      task_id: "tsk_done", status: "completed", prompt: "x", started_at: "t", ended_at: "t",
      tokens_in: 1, tokens_out: 1, iterations_used: 1, result: { output: "done" }, error: null })));
    server.use(http.get("/v1/containers/con_1/tasks/tsk_done/events", () =>
      HttpResponse.json({ events: [] })));

    renderWithProviders(
      <ChatTurn cid="con_1" taskId="tsk_done" prompt="x" initialStatus="completed" />,
    );

    await screen.findByText(/open full view/i);
    expect(screen.queryByRole("button", { name: /stop/i })).not.toBeInTheDocument();
  });
});

describe("ChatTurn — refreshing stale session state on completion", () => {
  it("refetches the sessions list when the streamed task reaches a terminal status", async () => {
    // A session's "busy" flag is only known via GET .../sessions — mount a
    // real SessionPicker alongside the turn (as the submit page does) so
    // there's an active observer for invalidateQueries to actually refetch,
    // and count calls to prove a real network refetch happens, not just that
    // nothing crashes.
    let sessionsCalls = 0;
    server.use(http.get("/v1/containers/con_1/sessions", () => {
      sessionsCalls++;
      return HttpResponse.json({ sessions: [] });
    }));
    server.use(http.get("/v1/containers/con_1/tasks/tsk_finishing", () => HttpResponse.json({
      task_id: "tsk_finishing", status: "running", prompt: "x", started_at: "t", ended_at: null,
      tokens_in: 0, tokens_out: 0, iterations_used: 0, result: null, error: null,
    })));
    server.use(http.get("/v1/containers/con_1/tasks/tsk_finishing/events", () =>
      HttpResponse.json({ events: [] })));

    // This turn's stream opens like normal but withholds its terminal event
    // until the test explicitly delivers it below — otherwise onOpen and a
    // synchronous onEvent would both land in the same tick, leaving no real
    // "still running" checkpoint to compare the post-completion count against.
    let deliverTerminal: (() => void) | null = null;
    vi.mocked(subscribeEvents).mockImplementationOnce((_cid, _tid, opts) => {
      opts.onOpen?.();
      deliverTerminal = () =>
        opts.onEvent({ seq: 1, type: "status_change", ts: "t", payload: { from: "running", to: "completed" } });
      return () => {};
    });

    renderWithProviders(
      <>
        <SessionPicker cid="con_1" sessionId={null} onChange={() => {}} />
        <ChatTurn cid="con_1" taskId="tsk_finishing" prompt="x" initialStatus="running" />
      </>,
    );

    await waitFor(() => expect(sessionsCalls).toBeGreaterThan(0));
    expect(await screen.findByRole("button", { name: /stop/i })).toBeInTheDocument(); // still running
    const callsWhileRunning = sessionsCalls;

    act(() => { deliverTerminal?.(); });

    await waitFor(() => expect(screen.queryByRole("button", { name: /stop/i })).not.toBeInTheDocument());
    await waitFor(() => expect(sessionsCalls).toBeGreaterThan(callsWhileRunning));
  });
});
