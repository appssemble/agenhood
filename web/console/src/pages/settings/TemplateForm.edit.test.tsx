import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import { AuthProvider } from "../../auth/AuthProvider";
import TemplateForm from "./TemplateForm";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({ id: "tpl_t" }),     // :id present -> edit mode
  useNavigate: () => navigate,
}));

const vanillaTpl = {
  id: "tpl_v", tenant_id: null, name: "Vanilla", driver: "vanilla", model: "claude-sonnet-4-6",
  system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] }, skills: [], limits: {}, is_builtin: true,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file"], tools_user_editable: true, supports_context: true },
  available_tool_specs: [{ name: "read_file", description: "", input_schema: {}, requires_image_feature: null }],
};
const opencodeTpl = {
  ...vanillaTpl, id: "tpl_o", driver: "opencode",
  driver_template: { driver: "opencode", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: false },
  available_tool_specs: [],
};

const existingTpl = {
  ...vanillaTpl, id: "tpl_t", tenant_id: "t", name: "My reviewer", driver: "vanilla", model: "claude-sonnet-4-6",
  system_prompt: "Original prompt", skills: [], limits: {}, is_builtin: false,
};

function setup() {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "admin", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla", "opencode", "codex"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
  server.use(http.get("/v1/models", () => HttpResponse.json({ models: [
    { id: "claude-sonnet-4-6", provider: "anthropic", label: "claude-sonnet-4-6", category: "api_key", drivers: ["vanilla", "opencode", "codex"], available: true, requires: [] },
  ] })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [vanillaTpl, opencodeTpl] })));
  server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [
    { id: "skl_1", name: "git-release", description: "", enabled: true, created_at: null, updated_at: null },
  ] })));
}

describe("TemplateForm (edit mode)", () => {
  it("prefills from the template and PATCHes the edited fields", async () => {
    setup();
    server.use(http.get("/v1/templates/tpl_t", () => HttpResponse.json(existingTpl)));
    let patched: any = null;
    server.use(http.patch("/v1/templates/tpl_t", async ({ request }) => { patched = await request.json(); return HttpResponse.json({ ...existingTpl }); }));
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);

    const nameInput = await screen.findByLabelText("Name");
    await waitFor(() => expect(nameInput).toHaveValue("My reviewer"));

    const promptInput = screen.getByLabelText("System prompt");
    await userEvent.clear(promptInput);
    await userEvent.type(promptInput, "Edited prompt");
    await userEvent.click(screen.getByRole("button", { name: /Save template/i }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched.name).toBe("My reviewer");
    expect(patched.system_prompt).toBe("Edited prompt");
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/templates"));
  });

  it("shows an error state when the template fetch fails", async () => {
    setup();
    server.use(http.get("/v1/templates/tpl_t", () => new HttpResponse(null, { status: 404 })));
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);

    expect(await screen.findByText(/Couldn't load this template/i)).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });
});
