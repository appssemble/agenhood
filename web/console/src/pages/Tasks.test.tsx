import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import Tasks from "./Tasks";

describe("Tasks (cross-fleet activity)", () => {
  beforeEach(() => {
    server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [
      { task_id: "tsk_1", container_id: "cnt_1", container_name: "web-support", status: "running", prompt: "investigate ticket", tokens_in: 100, tokens_out: 200, created_at: "2026-06-13T10:00:00Z" },
      { task_id: "tsk_2", container_id: "cnt_2", container_name: "qa-runner", status: "completed", prompt: "run suite", tokens_in: 300, tokens_out: 400, created_at: "2026-06-13T09:00:00Z" },
    ] })));
  });

  it("lists tasks across the fleet with a link into each", async () => {
    renderWithProviders(<Tasks />);
    await waitFor(() => expect(screen.getByText("investigate ticket")).toBeInTheDocument());
    expect(screen.getByText("run suite")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /web-support/ })).toHaveAttribute("href", "/containers/cnt_1/tasks/tsk_1");
  });

  it("filters by status", async () => {
    renderWithProviders(<Tasks />);
    await waitFor(() => expect(screen.getByText("investigate ticket")).toBeInTheDocument());
    screen.getByRole("button", { name: "Running" }).click();
    await waitFor(() => expect(screen.queryByText("run suite")).toBeNull());
    expect(screen.getByText("investigate ticket")).toBeInTheDocument();
  });
});
