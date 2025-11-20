import { describe, it, expect } from "vitest";
import { screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useLocation } from "react-router-dom";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import Containers from "./Containers";

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

function ctr(over: Partial<any> = {}) {
  return { id: "con_1", name: "research-analyst-prod", external_id: null, status: "running", image_variant: "full", image_tag: "v",
    config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
    metadata: {}, last_task_at: null, created_at: "t", error_message: null, ...over };
}
function meAdmin() {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "Davis", email: "d@x.io", role: "admin", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
}

describe("Containers", () => {
  it("lists containers with lifecycle status", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr(), ctr({ id: "con_2", name: "contracts-ingest", status: "error" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    expect(await screen.findByText("research-analyst-prod")).toBeInTheDocument();
    expect(screen.getByText("contracts-ingest")).toBeInTheDocument();
  });

  it("filters the table with the search box below the headline", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr(), ctr({ id: "con_2", name: "contracts-ingest", status: "error" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    expect(await screen.findByText("research-analyst-prod")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/search containers/i), "contracts");
    expect(screen.queryByText("research-analyst-prod")).toBeNull();
    expect(screen.getByText("contracts-ingest")).toBeInTheDocument();
  });

  it("shows Recover for an errored container but not a running one", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "running" }), ctr({ id: "con_2", name: "contracts-ingest", status: "error" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const errored = (await screen.findByText("contracts-ingest")).closest("tr")!;
    expect(within(errored).getByRole("button", { name: /Recover/i })).toBeInTheDocument();
    const running = screen.getByText("research-analyst-prod").closest("tr")!;
    expect(within(running).queryByRole("button", { name: /Recover/i })).not.toBeInTheDocument();
  });

  it("offers delete on a running container for admins", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "running" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    expect(within(row).getByRole("button", { name: /^Delete$/i })).toBeInTheDocument();
  });

  it("offers delete (and recover) on an errored container for admins", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "error" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    expect(within(row).getByRole("button", { name: /^Recover$/i })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /^Delete$/i })).toBeInTheDocument();
  });

  it("offers Force pause after pause is rejected 409 on a busy container", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr()] })));
    server.use(http.post("/v1/containers/con_1/pause", async ({ request }) => {
      const body = (await request.json()) as { force?: boolean };
      if (!body.force) return HttpResponse.json({ error: { code: "container_not_runnable", message: "Has 2 running tasks" } }, { status: 409 });
      return HttpResponse.json({});
    }));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /^Pause$/i }));
    // 409 → an inline force-pause confirm appears
    expect(await screen.findByRole("button", { name: /Force pause/i })).toBeInTheDocument();
  });

  it("opens a destroy modal for admins", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "paused" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /Destroy/i }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/Destroy container/i);
  });

  it("destroy modal explains the data is kept", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "paused" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /^Destroy$/i }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/keeps the data/i);
  });

  it("offers a permanent delete for admins", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "archived" })] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /^Delete$/i }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/permanently/i);
  });

  it("confirming delete fires the DELETE request", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr({ status: "archived" })] })));
    let deleted = false;
    server.use(http.delete("/v1/containers/con_1", () => { deleted = true; return HttpResponse.json({ id: "con_1", status: "deleted" }); }));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /^Delete$/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Delete forever/i }));
    await waitFor(() => expect(deleted).toBe(true));
  });

  it("no longer renders a per-row Open button", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr()] })));
    renderWithProviders(<AuthProvider><Containers /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    expect(within(row).queryByRole("link", { name: /^Open$/i })).toBeNull();
    expect(within(row).queryByRole("button", { name: /^Open$/i })).toBeNull();
  });

  it("opens the container when its row is clicked", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr()] })));
    renderWithProviders(<AuthProvider><Containers /><LocationProbe /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(row);
    expect(screen.getByTestId("loc").textContent).toBe("/containers/con_1");
  });

  it("clicking an in-row control (pin) does not open the container", async () => {
    meAdmin();
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [ctr()] })));
    renderWithProviders(<AuthProvider><Containers /><LocationProbe /></AuthProvider>);
    const row = (await screen.findByText("research-analyst-prod")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /Pin container/i }));
    expect(screen.getByTestId("loc").textContent).toBe("/");
  });
});
