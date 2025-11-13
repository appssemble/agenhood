import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "../components/Toast";
import { server } from "../test/server";
import { routes } from "./router";

function meAs(role: "admin" | "member") {
  return { id: "u", tenant_id: "t", name: "T", email: "t@x.io", role, is_staff: false, must_change_password: false,
    tenant: { id: "t", name: "A", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } } };
}
function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { router, jsx: (
    <QueryClientProvider client={qc}><ToastProvider><RouterProvider router={router} /></ToastProvider></QueryClientProvider>
  ) };
}

describe("router", () => {
  it("renders Containers under the shell at /containers", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("member"))));
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [] })));
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [] })));
    const { jsx } = renderAt("/containers");
    render(jsx);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Containers" })).toBeInTheDocument());
    // shell present
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("does not double-wrap pages in nested .page scroll containers", async () => {
    // The shell provides the single scroll viewport; each page renders its own
    // padded .page. A .page nested inside another .page creates two stacked
    // overflow:auto containers and clips content top/bottom while scrolling.
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("member"))));
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [] })));
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [] })));
    server.use(http.get("/v1/tasks", () => HttpResponse.json({ tasks: [] })));
    const { jsx } = renderAt("/");
    const { container } = render(jsx);
    await waitFor(() => expect(screen.getByText(/Start with/i)).toBeInTheDocument());
    expect(container.querySelector(".page .page")).toBeNull();
  });

  it("redirects a member away from /settings/users to Dashboard", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(meAs("member"))));
    server.use(http.get("/v1/containers", () => HttpResponse.json({ containers: [] })));
    server.use(http.get("/v1/templates", () => HttpResponse.json({ templates: [] })));
    const { jsx } = renderAt("/settings/users");
    render(jsx);
    await waitFor(() => expect(screen.getByText(/Start with/i)).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Users" })).not.toBeInTheDocument();
  });
});
