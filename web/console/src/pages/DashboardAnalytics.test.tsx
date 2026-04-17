import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import DashboardAnalytics from "./DashboardAnalytics";

function stubAll() {
  server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [
    { id: "c1", name: "support-bot", external_id: null, status: "running", image_variant: "full",
      image_tag: "v", config: { driver: "vanilla", model: "m", system_prompt: "",
      system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
      metadata: {}, last_task_at: null, created_at: "t", error_message: null },
  ] })));
  server.use(http.get("/v1/analytics/usage", () => HttpResponse.json({
    from: "f", to: "t", interval: "day",
    series: [{ start: "2026-05-27T00:00:00+00:00", tokens_in: 4200000, tokens_out: 1800000, tasks: 248, iterations: 1540 }],
  })));
  server.use(http.get("/v1/analytics/breakdown", ({ request }) => {
    const by = new URL(request.url).searchParams.get("by");
    if (by === "status") {
      return HttpResponse.json({ from: "f", to: "t", by, groups: [
        { key: "completed", label: "completed", tokens_in: 4000000, tokens_out: 1700000, tasks: 231, iterations: 1500 },
        { key: "failed", label: "failed", tokens_in: 200000, tokens_out: 100000, tasks: 17, iterations: 40 },
      ] });
    }
    return HttpResponse.json({ from: "f", to: "t", by, groups: [
      { key: "c1", label: "support-bot", tokens_in: 1400000, tokens_out: 500000, tasks: 62, iterations: 410 },
    ] });
  }));
  server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [
    { task_id: "t1", container_id: "c1", container_name: "support-bot", status: "completed",
      prompt: "p", tokens_in: 30000, tokens_out: 8000, created_at: "2026-06-03T11:58:00+00:00" },
  ] })));
}

describe("DashboardAnalytics", () => {
  it("composes health, KPIs, trend, leaderboard, and activity", async () => {
    stubAll();
    renderWithProviders(<DashboardAnalytics />, { route: "/?range=7d" });

    expect(await screen.findByTestId("count-running")).toHaveTextContent("1");
    // success rate = 231 / (231 + 17) = 93%
    expect(await screen.findByTestId("kpi-success")).toHaveTextContent("93%");
    expect(screen.getByTestId("kpi-tokens")).toHaveTextContent("6.0M");
    expect(await screen.findByTestId("trend-chart")).toBeInTheDocument();
    expect((await screen.findAllByTestId("lb-name"))[0]).toHaveTextContent("support-bot");
    expect(screen.getByRole("button", { name: "7d" }).className).toMatch(/active/);
  });

  it("isolates a failing analytics query to its card", async () => {
    stubAll();
    server.use(http.get("/v1/analytics/usage", () =>
      HttpResponse.json({ error: { code: "boom", message: "no" } }, { status: 500 })));
    renderWithProviders(<DashboardAnalytics />, { route: "/?range=7d" });
    // health still renders from the (successful) containers query
    expect(await screen.findByTestId("count-running")).toHaveTextContent("1");
    // trend card shows its own error, not a blank page
    expect(await screen.findByText(/couldn't load the usage trend/i)).toBeInTheDocument();
  });
});
