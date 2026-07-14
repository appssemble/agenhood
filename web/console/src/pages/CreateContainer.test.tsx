import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import CreateContainer from "./CreateContainer";

const nav = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => nav }));

function tpl(over: Partial<any> = {}) {
  return { id: "tpl_1", tenant_id: null, name: "Research assistant", driver: "vanilla", model: "claude-sonnet-4-6",
    system_prompt: "", system_prompt_mode: "augment", tools: ["read_file"], context: { variables: {}, text: null, files: [] },
    limits: {}, is_builtin: true,
    capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
    driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file"], tools_user_editable: true, supports_context: true },
    available_tool_specs: [], ...over };
}

function setupAuth() {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({
    id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "admin", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } },
  })));
  server.use(http.get("/v1/models", () => HttpResponse.json({ models: [
    { id: "claude-sonnet-4-6", provider: "anthropic", label: "claude-sonnet-4-6", category: "api_key", drivers: ["vanilla", "opencode"], available: true, requires: [] },
  ] })));
}

describe("CreateContainer", () => {
  it("creates a container from a chosen template and the selected variant", async () => {
    const user = userEvent.setup();
    setupAuth();
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [tpl()] })));
    let posted: any = null;
    server.use(http.post("/v1/containers", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "con_new", name: posted.name, status: "provisioning" });
    }));
    renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/name/i), "research-prod");
    await user.click(screen.getByRole("button", { name: /slim/i }));      // pick slim variant
    await user.click(screen.getByRole("button", { name: /Create container/i }));
    await waitFor(() => expect(posted).toMatchObject({
      name: "research-prod",
      template_id: "tpl_1",
      image_variant: "slim",
      config: expect.objectContaining({ model: "claude-sonnet-4-6" }),
    }));
    expect(nav).toHaveBeenCalledWith("/containers/con_new", { replace: true });
  });

  it("submits custom memory and cpu limits when provided", async () => {
    const user = userEvent.setup();
    setupAuth();
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [tpl()] })));
    let posted: any = null;
    server.use(http.post("/v1/containers", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "con_new", name: posted.name, status: "provisioning" });
    }));
    renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/name/i), "research-prod");
    await user.click(screen.getByLabelText(/memory/i));
    await user.click(screen.getByRole("option", { name: "1 GB" }));
    await user.click(screen.getByLabelText(/cpu/i));
    await user.click(screen.getByRole("option", { name: "0.5 CPU" }));
    await user.click(screen.getByRole("button", { name: /Create container/i }));
    await waitFor(() => expect(posted).toMatchObject({
      name: "research-prod",
      resource_limits: { mem_limit: "1g", cpus: 0.5 },
    }));
  });

  it("omits resource_limits when memory and cpu are left blank", async () => {
    const user = userEvent.setup();
    setupAuth();
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [tpl()] })));
    let posted: any = null;
    server.use(http.post("/v1/containers", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "con_new", name: posted.name, status: "provisioning" });
    }));
    renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/name/i), "research-prod");
    await user.click(screen.getByRole("button", { name: /Create container/i }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).not.toHaveProperty("resource_limits");
  });

  it("prefills the variant from the template and leaves memory/cpu to the backend", async () => {
    const user = userEvent.setup();
    setupAuth();
    server.use(http.get("/v1/templates", () => HttpResponse.json({
      templates: [tpl({ image_variant: "slim", mem_limit: "512m", cpus: 1 })],
    })));
    let posted: any = null;
    server.use(http.post("/v1/containers", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "con_new", name: "x", status: "provisioning" });
    }));
    renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
    // Memory/CPU default options relabel from the template's values
    expect(screen.getByText(/Template default \(512m\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Template default \(1 CPU\)/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/name/i), "research-prod");
    await user.click(screen.getByRole("button", { name: /Create container/i }));
    await waitFor(() => expect(posted).toMatchObject({ image_variant: "slim" }));
    expect(posted.resource_limits).toBeUndefined();   // backend layers the template values
  });

  it("explicit picks still override the template defaults", async () => {
    const user = userEvent.setup();
    setupAuth();
    server.use(http.get("/v1/templates", () => HttpResponse.json({
      templates: [tpl({ image_variant: "slim", mem_limit: "512m", cpus: 1 })],
    })));
    let posted: any = null;
    server.use(http.post("/v1/containers", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "con_new", name: "x", status: "provisioning" });
    }));
    renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/name/i), "research-prod");
    await user.click(screen.getByRole("button", { name: /full/i }));    // override variant
    await user.click(screen.getByLabelText(/^memory/i));                 // open memory dropdown
    await user.click(screen.getByRole("option", { name: /^2 GB$/i }));
    await user.click(screen.getByRole("button", { name: /Create container/i }));
    await waitFor(() => expect(posted).toMatchObject({
      image_variant: "full",
      resource_limits: { mem_limit: "2g" },
    }));
  });
});

test("shows the effort selector for a CLI driver and posts the picked value", async () => {
  const user = userEvent.setup();
  setupAuth();
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [
    tpl({ driver: "opencode", effort: null,
      driver_template: { driver: "opencode", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: true } }),
  ] })));
  let posted: any = null;
  server.use(http.post("/v1/containers", async ({ request }) => {
    posted = await request.json();
    return HttpResponse.json({ id: "con_new", name: posted.name, status: "provisioning" });
  }));
  renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
  expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
  await user.type(screen.getByLabelText(/name/i), "research-prod");
  await user.click(await screen.findByRole("button", { name: "high" }));
  await user.click(screen.getByRole("button", { name: /Create container/i }));
  await waitFor(() => expect(posted?.config).toMatchObject({ driver: "opencode", effort: "high" }));
});

test("hides the effort selector for a driver without effort support", async () => {
  setupAuth();
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [tpl()] })));
  renderWithProviders(<AuthProvider><CreateContainer /></AuthProvider>);
  expect(await screen.findByRole("button", { name: /Research assistant/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "high" })).not.toBeInTheDocument();
});
