import { describe, it, test, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import SubmitTask from "./SubmitTask";

const nav = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1" }), useNavigate: () => nav }));

const vanillaTpl = {
  id: "tpl_v", tenant_id: null, name: "Vanilla", driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] }, limits: {}, is_builtin: true,
  capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: [], tools_user_editable: true, supports_context: true }, available_tool_specs: [],
};
const opencodeTpl = { ...vanillaTpl, id: "tpl_o", driver: "opencode",
  capabilities: { supports_tools: false, supports_structured_output: false, supports_cancel: true, requires_image_feature: null },
  driver_template: { ...vanillaTpl.driver_template, driver: "opencode", tools_user_editable: false, supports_context: false } };

function setup(driver: "vanilla" | "opencode") {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "member", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla", "opencode"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [vanillaTpl, opencodeTpl] })));
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({ id: "con_1", name: "c", external_id: null, status: "running", image_variant: "full", image_tag: "v",
    config: { driver, model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } }, metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
  server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [] })));
  server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({ sessions: [] })));
}

describe("SubmitTask", () => {
  it("disables structured output when the driver lacks it (opencode)", async () => {
    setup("opencode");
    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    const structured = await screen.findByRole("button", { name: /structured/i });
    expect(structured).toBeDisabled();
  });

  it("enables structured output for vanilla", async () => {
    setup("vanilla");
    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    const structured = await screen.findByRole("button", { name: /structured/i });
    expect(structured).not.toBeDisabled();
  });

  it("submits the task body and navigates to the task viewer", async () => {
    setup("vanilla");
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => { body = await request.json(); return HttpResponse.json({ task_id: "tsk_9", status: "running", started_at: "t" }); }));
    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText(/Prompt/i), "Research pricing");
    await userEvent.click(screen.getByRole("button", { name: /Submit task/i }));
    await waitFor(() => expect(body.prompt).toBe("Research pricing"));
    expect(nav).toHaveBeenCalledWith("/containers/con_1/tasks/tsk_9");
  });

  it("omits effort from the payload when no override is picked (vanilla, no effort control shown)", async () => {
    setup("vanilla");
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => { body = await request.json(); return HttpResponse.json({ task_id: "tsk_10", status: "running", started_at: "t" }); }));
    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    expect(screen.queryByLabelText(/Effort override/i)).not.toBeInTheDocument();
    await userEvent.type(await screen.findByLabelText(/Prompt/i), "No effort here");
    await userEvent.click(screen.getByRole("button", { name: /Submit task/i }));
    await waitFor(() => expect(body.prompt).toBe("No effort here"));
    expect(body).not.toHaveProperty("effort");
  });

  it("includes the picked effort in the payload for an effort-capable driver (opencode)", async () => {
    setup("opencode");
    let body: any = null;
    server.use(http.post("/v1/containers/con_1/tasks", async ({ request }) => { body = await request.json(); return HttpResponse.json({ task_id: "tsk_11", status: "running", started_at: "t" }); }));
    renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText(/Prompt/i), "Research pricing");
    const effortSelect = await screen.findByLabelText(/Effort override/i);
    await userEvent.click(effortSelect);
    await userEvent.click(await screen.findByRole("option", { name: "high" }));
    await userEvent.click(screen.getByRole("button", { name: /Submit task/i }));
    await waitFor(() => expect(body.prompt).toBe("Research pricing"));
    expect(body.effort).toBe("high");
  });
});

test("pre-fills the prompt from the most recent task with a dismissable tag", async () => {
  server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "u", tenant_id: "t", name: "D", email: "d@x.io", role: "member", is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla", "opencode"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } })));
  server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [vanillaTpl, opencodeTpl] })));
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({ id: "con_1", name: "c", external_id: null, status: "running", image_variant: "full", image_tag: "v",
    config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } }, metadata: {}, last_task_at: null, created_at: "t", error_message: null })));
  server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [{ task_id: "tsk_9", prompt: "Prior prompt", status: "completed", started_at: "2026-06-02T00:00:00Z", ended_at: null, tokens_in: 0, tokens_out: 0, iterations_used: 0 }] })));
  server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({ sessions: [] })));

  renderWithProviders(<AuthProvider><SubmitTask /></AuthProvider>);

  const textarea = await screen.findByLabelText(/Prompt/i);
  await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe("Prior prompt"));
  expect(screen.getByText(/tsk_9/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Clear/i }));
  expect((textarea as HTMLTextAreaElement).value).toBe("");
});
