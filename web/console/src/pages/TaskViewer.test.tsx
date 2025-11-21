import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import TaskViewer from "./TaskViewer";

vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1", tid: "tsk_1" }) }));

class FakeEventSource {
  static last: FakeEventSource | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onopen: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.last = this;
    // simulate connection established immediately
    Promise.resolve().then(() => act(() => this.onopen?.()));
  }
  emit(ev: unknown) { act(() => this.onmessage?.({ data: JSON.stringify(ev) })); }
  close() {}
}
beforeEach(() => { (globalThis as any).EventSource = FakeEventSource; FakeEventSource.last = null; });

function runningTask() {
  server.use(http.get("/v1/containers/con_1/tasks/tsk_1", () => HttpResponse.json({
    task_id: "tsk_1", status: "running", prompt: "Research pricing", started_at: "2026-05-20T10:00:00Z",
    ended_at: null, tokens_in: 0, tokens_out: 0, iterations_used: 0, result: null, error: null })));
}

describe("TaskViewer (live SSE)", () => {
  it("renders each event type distinctly and appends incrementally", async () => {
    runningTask();
    renderWithProviders(<TaskViewer />);
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    const src = FakeEventSource.last!;
    src.emit({ seq: 1, type: "task_started", ts: "t", payload: { driver: "vanilla", model: "m" } });
    expect(await screen.findByText(/task started/i)).toBeInTheDocument();

    src.emit({ seq: 2, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: "I'll research three vendors." }] } });
    expect(await screen.findByText(/I'll research three vendors\./)).toBeInTheDocument();

    src.emit({ seq: 3, type: "tool_call", ts: "t", payload: { tool_use_id: "tc1", name: "web_search", input: { query: "acme pricing" } } });
    expect(await screen.findByText("web_search")).toBeInTheDocument();

    src.emit({ seq: 4, type: "tool_result", ts: "t", payload: { tool_use_id: "tc1", ok: true, content: "200 OK", duration_ms: 280 } });
    expect(await screen.findByText(/280/)).toBeInTheDocument();

    src.emit({ seq: 5, type: "file_changed", ts: "t", payload: { path: "/workspace/report.md", operation: "create", size: 2100 } });
    expect(await screen.findByText("/workspace/report.md")).toBeInTheDocument();

    src.emit({ seq: 6, type: "log", ts: "t", payload: { level: "warn", message: "Approaching token budget" } });
    expect(await screen.findByText(/Approaching token budget/)).toBeInTheDocument();

    // incremental: all six rows are present and ordered
    expect(screen.getAllByTestId("event-row")).toHaveLength(6);
  });

  it("updates the live token counter from token_update events", async () => {
    runningTask();
    renderWithProviders(<TaskViewer />);
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    FakeEventSource.last!.emit({ seq: 1, type: "token_update", ts: "t", payload: { tokens_in: 38200, tokens_out: 21800 } });
    expect(await screen.findByText(/60,000/)).toBeInTheDocument(); // 38200 + 21800
  });

  it("shows a connection-state indicator and flips to disconnected on error", async () => {
    runningTask();
    renderWithProviders(<TaskViewer />);
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    const src = FakeEventSource.last!;
    await waitFor(() => expect(screen.getByText(/live/i)).toBeInTheDocument());
    await act(async () => { src.onerror?.({}); });
    expect(await screen.findByText(/reconnecting|disconnected/i)).toBeInTheDocument();
  });

  it("cancels via an inline confirm", async () => {
    runningTask();
    let cancelled = false;
    server.use(http.post("/v1/containers/con_1/tasks/tsk_1/cancel", () => { cancelled = true; return HttpResponse.json({ task_id: "tsk_1", status: "cancelled" }); }));
    renderWithProviders(<TaskViewer />);
    await userEvent.click(await screen.findByRole("button", { name: /^Cancel$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Yes, cancel task/i }));
    await waitFor(() => expect(cancelled).toBe(true));
  });

  it("shows the result and a file download link on completion", async () => {
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1", () => HttpResponse.json({
      task_id: "tsk_1", status: "completed", prompt: "Research pricing", started_at: "2026-05-20T10:00:00Z",
      ended_at: "2026-05-20T10:02:14Z", tokens_in: 38200, tokens_out: 21800, iterations_used: 6,
      result: { success: true, output: "Done. See report.", files: ["/workspace/report.md"] }, error: null })));
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1/events", () => HttpResponse.json({ events: [] })));
    renderWithProviders(<TaskViewer />);
    expect(await screen.findByText(/Done\. See report\./)).toBeInTheDocument();
    const dl = await screen.findByRole("link", { name: /report\.md/i });
    expect(dl).toHaveAttribute("href", expect.stringContaining("/v1/containers/con_1/files/raw?path=%2Fworkspace%2Freport.md"));
  });

  it("replays recorded events in the Activity tab for a finished task", async () => {
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1", () => HttpResponse.json({
      task_id: "tsk_1", status: "completed", prompt: "Research pricing", started_at: "2026-05-20T10:00:00Z",
      ended_at: "2026-05-20T10:02:14Z", tokens_in: 38200, tokens_out: 21800, iterations_used: 6,
      result: { success: true, output: "Done. See report.", files: [] }, error: null })));
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1/events", () => HttpResponse.json({ events: [
      { seq: 1, type: "task_started", ts: "t", payload: { driver: "vanilla", model: "m" } },
      { seq: 2, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: "Replayed step." }] } },
    ] })));
    renderWithProviders(<TaskViewer />);
    // Lands on Result; switch to Activity to see the replay.
    await userEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));
    expect(await screen.findByText(/Replayed step\./)).toBeInTheDocument();
    expect(screen.getAllByTestId("event-row")).toHaveLength(2);
  });
});
