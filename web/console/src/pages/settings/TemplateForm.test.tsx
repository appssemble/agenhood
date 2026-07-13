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
  useParams: () => ({}),                 // no :id -> create mode
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

describe("TemplateForm (create mode)", () => {
  it("POSTs a new template with the entered fields", async () => {
    setup();
    let posted: any = null;
    server.use(http.post("/v1/templates", async ({ request }) => { posted = await request.json(); return HttpResponse.json({ ...vanillaTpl, id: "tpl_new", tenant_id: "t", is_builtin: false }); }));
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText("Name"), "Code reviewer");
    await userEvent.type(screen.getByLabelText("System prompt"), "Be terse.");
    await userEvent.click(screen.getByRole("button", { name: /Save template/i }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.name).toBe("Code reviewer");
    expect(posted.driver).toBe("vanilla");
    expect(posted.system_prompt).toBe("Be terse.");
    expect(posted.model).toBe(null);                 // model untouched -> null
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/templates"));
  });

  it("switches sections when the driver changes (tools hidden, skills shown)", async () => {
    setup();
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);
    expect(await screen.findByLabelText("read_file")).toBeInTheDocument();
    // "opencode" has no DRIVER_LABEL override, so its card aria-label is the raw id
    await userEvent.click(screen.getByRole("radio", { name: "opencode" }));
    await waitFor(() => expect(screen.queryByLabelText("read_file")).not.toBeInTheDocument());
    expect(screen.getByLabelText("git-release")).toBeInTheDocument();
  });

  it("clears effort when switching to a driver that doesn't support it", async () => {
    setup();
    let posted: any = null;
    server.use(http.post("/v1/templates", async ({ request }) => { posted = await request.json(); return HttpResponse.json({ ...vanillaTpl, id: "tpl_new", tenant_id: "t", is_builtin: false }); }));
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);
    await screen.findByLabelText("read_file");
    // "vanilla" has a DRIVER_LABEL override ("barebones"); switch to opencode
    // (an effort driver), set an effort, then switch back to vanilla.
    await userEvent.click(screen.getByRole("radio", { name: "opencode" }));
    await userEvent.click(await screen.findByRole("button", { name: "High" }));
    await userEvent.click(screen.getByRole("radio", { name: "barebones" }));
    await userEvent.type(screen.getByLabelText("Name"), "T");
    await userEvent.click(screen.getByRole("button", { name: /Save template/i }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.driver).toBe("vanilla");
    expect(posted.effort).toBe(null);
  });
});
