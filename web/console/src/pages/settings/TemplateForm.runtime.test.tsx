import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import { AuthProvider } from "../../auth/AuthProvider";
import TemplateForm from "./TemplateForm";

const nav = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => nav,
  useParams: () => ({ id: "tpl_1" }),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

const TPL = {
  id: "tpl_1", tenant_id: "t", name: "T", driver: "vanilla", model: "claude-sonnet-4-6",
  system_prompt: "", system_prompt_mode: "augment", tools: [], limits: {},
  context: { variables: {}, text: null, files: [] }, skills: [], mcp_servers: [],
  is_builtin: false, image_variant: "slim", mem_limit: "512m", cpus: 1,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: [], tools_user_editable: true, supports_context: true },
  available_tool_specs: [],
};

function setup() {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({
    id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "admin", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } },
  })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [TPL] })));
  server.use(http.get("/v1/templates/tpl_1", () => HttpResponse.json(TPL)));
  server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [] })));
  server.use(http.get("/v1/mcp-servers", () => HttpResponse.json({ mcp_servers: [] })));
}

describe("TemplateForm runtime section", () => {
  it("loads runtime values from the template and saves them nullable", async () => {
    const user = userEvent.setup();
    setup();
    let patched: any = null;
    server.use(http.patch("/v1/templates/tpl_1", async ({ request }) => {
      patched = await request.json();
      return HttpResponse.json(TPL);
    }));
    renderWithProviders(<AuthProvider><TemplateForm /></AuthProvider>);
    // Runtime dropdowns show the template's stored values
    expect(await screen.findByLabelText(/image variant/i)).toHaveTextContent(/slim/i);
    expect(screen.getByLabelText(/^memory/i)).toHaveTextContent("512 MB");
    expect(screen.getByLabelText(/^cpus/i)).toHaveTextContent("1 CPU");
    await user.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(patched).toMatchObject({
      image_variant: "slim", mem_limit: "512m", cpus: 1,
    }));
  });
});
