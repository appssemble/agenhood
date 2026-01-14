import { describe, it, expect } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import { AuthProvider } from "../../auth/AuthProvider";
import Templates from "./Templates";

function meAs(role: "admin" | "member") {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role, is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
}
const builtin = { id: "tpl_b", tenant_id: null, name: "Research assistant", driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], skills: [], context: { variables: {}, text: null, files: [] }, limits: {}, is_builtin: true,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: [], tools_user_editable: true, supports_context: true }, available_tool_specs: [] };

describe("Templates", () => {
  it("lets a member clone a built-in but not delete it", async () => {
    meAs("member");
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [builtin] })));
    let cloned = false;
    server.use(http.post("/v1/templates/tpl_b/clone", () => { cloned = true; return HttpResponse.json({ ...builtin, id: "tpl_clone", tenant_id: "t", is_builtin: false }); }));
    renderWithProviders(<AuthProvider><Templates /></AuthProvider>);
    const card = (await screen.findByText("Research assistant")).closest("[data-template]")!;
    expect(within(card as HTMLElement).queryByRole("button", { name: /Delete/i })).not.toBeInTheDocument();
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Clone/i }));
    await waitFor(() => expect(cloned).toBe(true));
  });

  it("lets an admin delete a tenant template", async () => {
    meAs("admin");
    const tenantTpl = { ...builtin, id: "tpl_t", tenant_id: "t", is_builtin: false, name: "My template" };
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [builtin, tenantTpl] })));
    let deleted = false;
    server.use(http.delete("/v1/templates/tpl_t", () => { deleted = true; return new HttpResponse(null, { status: 204 }); }));
    renderWithProviders(<AuthProvider><Templates /></AuthProvider>);
    const card = (await screen.findByText("My template")).closest("[data-template]")!;
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Delete/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog as HTMLElement).getByRole("button", { name: /^Delete$/i }));  // confirm modal
    await waitFor(() => expect(deleted).toBe(true));
  });

  it("shows the New template button for admins and filters by search", async () => {
    meAs("admin");
    const tenantTpl = { ...builtin, id: "tpl_t", tenant_id: "t", is_builtin: false, name: "My reviewer" };
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [builtin, tenantTpl] })));
    renderWithProviders(<AuthProvider><Templates /></AuthProvider>);
    expect(await screen.findByRole("link", { name: /New template/i })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Search templates/i), "reviewer");
    await waitFor(() => expect(screen.queryByText("Research assistant")).not.toBeInTheDocument());
    expect(screen.getByText("My reviewer")).toBeInTheDocument();
  });

  it("hides the New template button for members", async () => {
    meAs("member");
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [builtin] })));
    renderWithProviders(<AuthProvider><Templates /></AuthProvider>);
    await screen.findByText("Research assistant");
    expect(screen.queryByRole("link", { name: /New template/i })).not.toBeInTheDocument();
  });
});
