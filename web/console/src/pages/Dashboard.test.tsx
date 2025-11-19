import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import Dashboard from "./Dashboard";

describe("Dashboard", () => {
  it("shows analytics when containers exist", async () => {
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [] })));
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [
      { id: "c1", name: "research-analyst-prod", external_id: null, status: "running", image_variant: "full", image_tag: "v", config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } }, metadata: {}, last_task_at: null, created_at: "t", error_message: null },
    ] })));
    server.use(http.get("/v1/analytics/usage", () => HttpResponse.json({ from: "f", to: "t", interval: "day", series: [] })));
    server.use(http.get("/v1/analytics/breakdown", () => HttpResponse.json({ from: "f", to: "t", by: "status", groups: [] })));
    server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [] })));
    renderWithProviders(<Dashboard />);
    expect(await screen.findByTestId("count-running")).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "7d" })).toBeInTheDocument();
  });

  it("shows the first-run empty state when there are no containers", async () => {
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [] })));
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [] })));
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText(/Start with/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Create.*container/i })).toBeInTheDocument();
  });
});
