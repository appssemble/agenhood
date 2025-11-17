import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { Panel } from "./Panel";
import type { Me, Container } from "../api/types";

const member = { name: "Mara", role: "member", is_staff: false } as Me;
const admin = { name: "Ada", role: "admin", is_staff: false } as Me;
const containers = [{ id: "cnt_1", name: "web-support", external_id: "cnt_1", status: "running", image_variant: "full", config: { driver: "opencode", model: "m" } } as Container];

describe("Panel", () => {
  beforeEach(() => {
    server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [] })));
  });

  it("settings panel: admin-only items gated; no Profile (moved to rail avatar), Templates/Skills in Fleet", () => {
    const { rerender } = renderWithProviders(<Panel mode="settings" user={member} containers={containers} cid={null} />);
    expect(screen.queryByRole("link", { name: "Profile" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Templates" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
    expect(screen.queryByRole("link", { name: "API keys" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Credentials" })).toBeNull();

    rerender(<Panel mode="settings" user={admin} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "API keys" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Credentials" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Skills" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Profile" })).toBeNull();
  });

  it("fleet panel: Templates (all) above Containers, Skills admin-only", () => {
    const { rerender } = renderWithProviders(<Panel mode="fleet" user={member} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: "Templates" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Skills" })).toBeNull();
    expect(screen.getByRole("link", { name: /Containers/ })).toBeInTheDocument();

    rerender(<Panel mode="fleet" user={admin} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: "Skills" })).toBeInTheDocument();
  });

  it("container mode renders the container panel", () => {
    renderWithProviders(<Panel mode="container" user={member} containers={containers} cid="cnt_1" />);
    expect(screen.getByRole("link", { name: "Configuration" })).toBeInTheDocument();
  });

  it("tasks mode renders an Activity link", () => {
    renderWithProviders(<Panel mode="tasks" user={member} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: /Activity/ })).toHaveAttribute("href", "/tasks");
  });

  it("workflows mode renders Prompts, Workflows and Scheduled runs nav links", () => {
    renderWithProviders(<Panel mode="workflows" user={member} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: "Prompts" })).toHaveAttribute("href", "/prompts");
    expect(screen.getByRole("link", { name: "Workflows" })).toHaveAttribute("href", "/workflows");
    expect(screen.getByRole("link", { name: "Scheduled runs" })).toHaveAttribute("href", "/schedules");
  });

  it("staff mode renders a Staff overview link", () => {
    renderWithProviders(<Panel mode="staff" user={member} containers={containers} cid={null} />);
    expect(screen.getByRole("link", { name: /Overview/ })).toHaveAttribute("href", "/staff");
  });
});
