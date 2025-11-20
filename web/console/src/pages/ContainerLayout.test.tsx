import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import ContainerLayout from "./ContainerLayout";

vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1" }), Outlet: () => <div>outlet</div> }));

describe("ContainerLayout", () => {
  it("renders the summary strip with name, status, driver/model", async () => {
    server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({
      id: "con_1", name: "research-analyst-prod", external_id: null, status: "running", image_variant: "full", image_tag: "v",
      config: { driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
      metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
    server.use(http.get("*/v1/containers/*/tasks", () => HttpResponse.json({ tasks: [] })));
    renderWithProviders(<ContainerLayout />);
    await waitFor(() => expect(screen.getByText("research-analyst-prod")).toBeInTheDocument());
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText(/vanilla · claude-sonnet-4-6/)).toBeInTheDocument();
    expect(screen.getByText("outlet")).toBeInTheDocument();
  });

  it("does not render an in-page tab bar (nav moved to the side panel)", async () => {
    server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({
      id: "con_1", name: "research-analyst-prod", external_id: null, status: "running", image_variant: "full", image_tag: "v",
      config: { driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
      metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
    server.use(http.get("*/v1/containers/*/tasks", () => HttpResponse.json({ tasks: [] })));
    renderWithProviders(<ContainerLayout />);
    await waitFor(() => expect(screen.getByText("research-analyst-prod")).toBeInTheDocument());
    expect(document.querySelector(".tabs")).toBeNull();
  });
});
