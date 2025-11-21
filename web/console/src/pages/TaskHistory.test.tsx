import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import TaskHistory from "./TaskHistory";

vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1" }) }));

const CONTAINER_STUB = { id: "con_1", name: "Test", external_id: null, status: "running", image_variant: "full", image_tag: "latest",
  config: { driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "Current", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
  metadata: {}, last_task_at: null, created_at: "t", error_message: null };

describe("TaskHistory", () => {
  it("lists past tasks and shows the config snapshot for a selected one", async () => {
    server.use(
      http.get("/v1/containers/con_1", () => HttpResponse.json(CONTAINER_STUB)),
      http.get("/v1/containers/con_1/tasks/tsk_1/events", () => HttpResponse.json({ events: [] })),
      http.get("/v1/containers/con_1/tasks/tsk_2/events", () => HttpResponse.json({ events: [] })),
    );
    server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [
      { task_id: "tsk_1", status: "completed", prompt: "Summarize Q3 contracts", started_at: "t", ended_at: "t", tokens_in: 8000, tokens_out: 4401, iterations_used: 5,
        config_snapshot: { driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "Old", system_prompt_mode: "replace", tools: ["web_fetch"], context: { variables: {}, text: null, files: [] } } },
      { task_id: "tsk_2", status: "timed_out", prompt: "Build investor brief", started_at: "t", ended_at: "t", tokens_in: 80000, tokens_out: 9302, iterations_used: 50,
        config_snapshot: { driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "New", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } } },
    ] })));
    renderWithProviders(<TaskHistory />);
    expect(await screen.findByText("Summarize Q3 contracts")).toBeInTheDocument();
    expect(screen.getByText("Build investor brief")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Summarize Q3 contracts"));
    await waitFor(() => expect(screen.getByText(/replace/)).toBeInTheDocument());     // snapshot prompt mode
    expect(screen.getByText(/web_fetch/)).toBeInTheDocument();                        // snapshot tools
  });

  it("replays events for a finished task", async () => {
    server.use(http.get("/v1/containers/con_1", () => HttpResponse.json(CONTAINER_STUB)));
    server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [
      { task_id: "tsk_1", status: "completed", prompt: "Summarize", started_at: "t", ended_at: "t", tokens_in: 1, tokens_out: 1, iterations_used: 1,
        config_snapshot: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } } },
    ] })));
    // history replays events over plain GET (test renders them from the JSON list endpoint variant)
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1/events", () => HttpResponse.json({ events: [
      { seq: 1, type: "task_started", ts: "t", payload: { driver: "vanilla", model: "m" } },
      { seq: 2, type: "assistant_message", ts: "t", payload: { content: [{ type: "text", text: "Replayed message" }] } },
    ] })));
    renderWithProviders(<TaskHistory />);
    await userEvent.click(await screen.findByText("Summarize"));
    expect(await screen.findByText("Replayed message")).toBeInTheDocument();
  });
});
