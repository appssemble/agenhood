import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import { AppShell } from "./AppShell";

function meAs(role: "admin" | "member", is_staff = false) {
  return {
    id: "usr_1", tenant_id: "tnt_1", name: "Test", email: "t@x.io", role, is_staff,
    must_change_password: false,
    active_tenant_id: null,
    tenants: [],
    tenant: { id: "tnt_1", name: "Acme", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } },
  };
}

describe("AppShell fleet-console nav", () => {
  beforeEach(() => {
    server.use(
      http.get("/v1/containers", () => HttpResponse.json({ containers: [] })),
      http.get("/v1/templates", () => HttpResponse.json({ templates: [] })),
      http.get("/v1/tasks", () => HttpResponse.json({ tasks: [] })),
    );
  });

  it("rail shows Dashboard/Fleet/Tasks/Settings for everyone; Staff only for staff", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("member"))));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>);
    await waitFor(() => expect(screen.getByRole("link", { name: "Fleet" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Staff" })).toBeNull();
  });

  it("shows Staff in the rail for staff users", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json({ ...meAs("admin", true), tenant_id: null, tenant: null })));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>);
    await waitFor(() => expect(screen.getByRole("link", { name: "Staff" })).toBeInTheDocument());
  });

  it("redirects a member away from admin-only settings", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("member"))));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/settings/users" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
    expect(screen.queryByRole("link", { name: "API keys" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Credentials" })).toBeNull();
  });

  it("settings section shows admin-only items for an admin", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("admin"))));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/settings/users" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "API keys" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Credentials" })).toBeInTheDocument();
    // Profile is no longer a settings entry; it lives on the rail avatar instead.
    expect(screen.queryByRole("navigation", { name: "Settings navigation" })).toBeInTheDocument();
  });

  it("renders the side panel on the Fleet section", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("admin"))));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/containers" });
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Fleet navigation" })).toBeInTheDocument());
  });

  it("omits the side panel on Dashboard and Tasks", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("admin"))));
    const dash = renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument());
    expect(screen.queryByRole("navigation", { name: "Fleet navigation" })).toBeNull();
    dash.unmount();
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/tasks" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument());
    expect(screen.queryByRole("navigation", { name: "Tasks navigation" })).toBeNull();
  });

  it("collapses the side panel via the edge toggle", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("admin"))));
    renderWithProviders(<AuthProvider><AppShell /></AuthProvider>, { route: "/containers" });
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Fleet navigation" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Collapse panel" }));
    expect(screen.queryByRole("navigation", { name: "Fleet navigation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Expand panel" })).toBeInTheDocument();
  });
});
