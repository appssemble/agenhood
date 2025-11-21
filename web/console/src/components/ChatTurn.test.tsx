import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { ChatTurn } from "./ChatTurn";

// Keep the streamed task RUNNING: emit one non-terminal event and never a
// terminal status_change, so the Stop affordance stays visible.
vi.mock("../api/events", () => ({
  subscribeEvents: (
    _cid: string,
    _tid: string,
    opts: { onOpen?: () => void; onEvent: (e: unknown) => void },
  ) => {
    opts.onOpen?.();
    opts.onEvent({ seq: 1, type: "tool_call", ts: "t", payload: { name: "bash", input: {} } });
    return () => {};
  },
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
