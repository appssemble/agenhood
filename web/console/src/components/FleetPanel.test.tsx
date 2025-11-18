import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { FleetPanel } from "./FleetPanel";
import type { Container, Me } from "../api/types";

const containers = [
  { id: "cnt_1", name: "web-support", external_id: "cnt_1", status: "running", last_task_at: "2026-06-13T10:00:00Z", image_variant: "full", config: { driver: "opencode", model: "m" } } as Container,
  { id: "cnt_2", name: "qa-runner", external_id: "cnt_2", status: "paused", last_task_at: "2026-06-12T10:00:00Z", image_variant: "full", config: { driver: "opencode", model: "m" } } as Container,
];
const member = { name: "Mara", role: "member", is_staff: false } as Me;
const admin = { name: "Ada", role: "admin", is_staff: false } as Me;

describe("FleetPanel", () => {
  beforeEach(() => {
    server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [
      { task_id: "tsk_1", container_id: "cnt_1", container_name: "web-support", status: "running", prompt: "go", tokens_in: 1, tokens_out: 2, created_at: "2026-06-13T10:00:00Z" },
    ] })));
  });

  it("renders the Containers link and the container list (Dashboard moved to the rail)", async () => {
    renderWithProviders(<FleetPanel containers={containers} user={member} />);
    expect(screen.queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(screen.getByRole("link", { name: /Containers/ })).toHaveAttribute("href", "/containers");
    expect(screen.getByRole("link", { name: /web-support/ })).toHaveAttribute("href", "/containers/cnt_1");
    expect(screen.getByRole("link", { name: /qa-runner/ })).toHaveAttribute("href", "/containers/cnt_2");
  });

  it("shows a live chip for a container with a running task", async () => {
    renderWithProviders(<FleetPanel containers={containers} user={member} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /watch running task/i })).toBeInTheDocument());
  });

  it("shows Templates (all) above Containers, Skills only for admins", () => {
    const { rerender } = renderWithProviders(<FleetPanel containers={containers} user={member} />);
    expect(screen.getByRole("link", { name: "Templates" })).toHaveAttribute("href", "/settings/templates");
    expect(screen.queryByRole("link", { name: "Skills" })).toBeNull();
    rerender(<FleetPanel containers={containers} user={admin} />);
    expect(screen.getByRole("link", { name: "Skills" })).toHaveAttribute("href", "/settings/skills");
  });
});
