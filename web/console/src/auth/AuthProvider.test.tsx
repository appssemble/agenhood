import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";

function Probe() {
  const { user } = useAuth();
  return <div>role:{user?.role ?? "none"}</div>;
}

describe("AuthProvider", () => {
  it("loads /auth/me and exposes the user + role", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json({
      id: "usr_1", tenant_id: "tnt_1", name: "Davis", email: "d@x.io", role: "admin",
      is_staff: false, must_change_password: false,
      tenant: { id: "tnt_1", name: "Acme", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 200000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } },
    })));
    renderWithProviders(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText("role:admin")).toBeInTheDocument();
  });
});
