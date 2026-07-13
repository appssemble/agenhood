import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import Configuration from "./Configuration";

vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1" }) }));

const vanillaTpl = {
  id: "tpl_v", tenant_id: null, name: "Vanilla", driver: "vanilla", model: "claude-sonnet-4-6",
  system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] }, limits: {}, is_builtin: true,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file", "web_fetch"], tools_user_editable: true, supports_context: true },
  available_tool_specs: [
    { name: "read_file", description: "", input_schema: {}, requires_image_feature: null },
    { name: "web_fetch", description: "", input_schema: {}, requires_image_feature: "chromium" },
  ],
};
const opencodeTpl = {
  ...vanillaTpl, id: "tpl_o", name: "Opencode", driver: "opencode",
  capabilities: { supports_tools: false, supports_structured_output: false, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "opencode", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: false },
  available_tool_specs: [],
};
const codexTpl = {
  ...vanillaTpl, id: "tpl_c", name: "Codex", driver: "codex",
  capabilities: { supports_tools: false, supports_structured_output: false, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "codex", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: false },
  available_tool_specs: [],
};

function setup(over: Partial<any> = {}) {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "admin", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla", "opencode", "codex"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
  server.use(http.get("/v1/models", () => HttpResponse.json({ models: [
    { id: "claude-sonnet-4-6", provider: "anthropic", label: "claude-sonnet-4-6", category: "api_key", drivers: ["vanilla", "opencode", "codex"], available: true, requires: [] },
    { id: "claude-haiku-4-5", provider: "anthropic", label: "claude-haiku-4-5", category: "api_key", drivers: ["vanilla", "opencode", "codex"], available: true, requires: [] },
  ] })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [vanillaTpl, opencodeTpl, codexTpl] })));
  server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [] })));
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({
    id: "con_1", name: "c", external_id: null, status: "running", image_variant: over.variant ?? "slim", image_tag: "v",
    config: { driver: over.driver ?? "vanilla", model: "claude-sonnet-4-6", system_prompt: "Be helpful.", system_prompt_mode: "augment", tools: over.tools ?? [], context: { variables: {}, text: null, files: [] }, effort: over.effort ?? null },
    metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
  server.use(http.get("/v1/containers/con_1/config", () => HttpResponse.json({
    config: { driver: over.driver ?? "vanilla", model: "claude-sonnet-4-6", system_prompt: "Be helpful.", system_prompt_mode: "augment", tools: over.tools ?? [], context: { variables: {}, text: null, files: [] }, effort: over.effort ?? null },
    assembled_prompt: "## SYSTEM\n..." })));
}

describe("Configuration editor (driver-aware)", () => {
  it("shows the tool picker for vanilla (tools_user_editable=true)", async () => {
    setup({ driver: "vanilla" });
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    expect(await screen.findByLabelText("read_file")).toBeInTheDocument();
    expect(screen.getByLabelText("web_fetch")).toBeInTheDocument();
  });

  it("hides the tool picker and context editor for opencode (tools_user_editable=false, supports_context=false)", async () => {
    setup({ driver: "opencode" });
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    await waitFor(() => expect(screen.getByText(/driver manages its own tools and context/i)).toBeInTheDocument());
    expect(screen.queryByLabelText("read_file")).not.toBeInTheDocument();
    expect(screen.queryByText(/Standing context/i)).not.toBeInTheDocument();
  });

  it("warns when a chosen tool needs chromium on a slim container", async () => {
    setup({ driver: "vanilla", variant: "slim", tools: [] });
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    await userEvent.click(await screen.findByLabelText("web_fetch"));   // enable a chromium tool
    // The warning itself names the slim variant (the read-only variant tag also
    // says "slim", so assert against the warning text specifically).
    expect(await screen.findByText(/full image variant/i)).toHaveTextContent(/slim/i);
  });

  it("updates the assembled-prompt preview as the system prompt is edited", async () => {
    setup({ driver: "vanilla", tools: ["read_file"] });
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    const preview = await screen.findByTestId("assembled-preview");
    const editor = screen.getByLabelText(/System prompt/i);
    await userEvent.clear(editor);
    await userEvent.type(editor, "Cite every source.");
    await waitFor(() => expect(preview).toHaveTextContent("Cite every source."));
    expect(preview).toHaveTextContent("## SYSTEM");        // augment scaffolding present
  });

  it("shows the assembled preview verbatim in replace mode", async () => {
    setup({ driver: "vanilla", tools: ["read_file"] });
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /Replace/i }));
    const editor = screen.getByLabelText(/System prompt/i);
    await userEvent.clear(editor);
    await userEvent.type(editor, "RAW VERBATIM PROMPT");
    const preview = screen.getByTestId("assembled-preview");
    await waitFor(() => expect(preview).toHaveTextContent("RAW VERBATIM PROMPT"));
    expect(preview).not.toHaveTextContent("## SYSTEM");   // nothing injected
  });

  it("PATCHes the config on save", async () => {
    setup({ driver: "vanilla", tools: ["read_file"] });
    let patched: any = null;
    server.use(http.patch("/v1/containers/con_1/config", async ({ request }) => { patched = await request.json(); return HttpResponse.json({ config: patched, assembled_prompt: "x" }); }));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    const editor = await screen.findByLabelText(/System prompt/i);
    await userEvent.type(editor, " More.");
    await userEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => expect(patched.system_prompt).toContain("More."));
  });

  it("marks the form dirty and saves when a per-container limit changes", async () => {
    setup({ driver: "vanilla", tools: ["read_file"] });
    let patched: any = null;
    server.use(http.patch("/v1/containers/con_1/config", async ({ request }) => { patched = await request.json(); return HttpResponse.json({ config: patched, assembled_prompt: "x" }); }));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);

    const maxTokens = await screen.findByLabelText("Max tokens");
    expect(maxTokens).toHaveValue(null);                       // blank = inherit tenant default
    await userEvent.type(maxTokens, "50000");

    // The unsaved-changes card appears once any limit changes.
    await waitFor(() => expect(screen.getByText(/unsaved change/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => expect(patched.max_tokens).toBe(50000));
  });

  it("shows the skills selector only for the opencode driver", async () => {
    setup({ driver: "opencode" });
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [
      { id: "skl_1", name: "git-release", description: "Make releases", body: "", enabled: true, created_at: null, updated_at: null },
    ] })));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    const checkbox = await screen.findByLabelText("git-release");
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    expect(checkbox).toBeChecked();              // selecting toggles config.skills
  });

  it("shows the skills selector for the codex driver too", async () => {
    setup({ driver: "codex" });
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [
      { id: "skl_1", name: "git-release", description: "Make releases", enabled: true, created_at: null, updated_at: null },
    ] })));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    const checkbox = await screen.findByLabelText("git-release");
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("hides the skills selector for non-opencode drivers", async () => {
    setup({ driver: "vanilla" });
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [
      { id: "skl_1", name: "git-release", description: "Make releases", body: "", enabled: true, created_at: null, updated_at: null },
    ] })));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    await waitFor(() => expect(screen.getByLabelText("Driver")).toBeInTheDocument());
    expect(screen.queryByLabelText("git-release")).not.toBeInTheDocument();
  });

  it("clears effort when switching to a driver that doesn't support it", async () => {
    setup({ driver: "opencode", effort: "high" });
    let patched: any = null;
    server.use(http.patch("/v1/containers/con_1/config", async ({ request }) => { patched = await request.json(); return HttpResponse.json({ config: patched, assembled_prompt: "x" }); }));
    renderWithProviders(<AuthProvider><Configuration /></AuthProvider>);
    await screen.findByLabelText("Driver");
    expect(screen.getByText("Effort")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Driver"));
    await userEvent.click(screen.getByRole("option", { name: "vanilla" }));
    // vanilla doesn't support effort — the field disappears and the value clears
    expect(screen.queryByText("Effort")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched.driver).toBe("vanilla");
    expect(patched.effort).toBe(null);
  });
});
