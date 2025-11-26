import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import Login from "./Login";

const nav = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => nav }));

describe("Login", () => {
  const ME = (overrides = {}) => ({
    id: "u", name: "U", email: "d@x.io", role: "member", is_staff: false,
    must_change_password: false, tenant: null, tenant_id: null,
    active_tenant_id: null, tenants: [], ...overrides,
  });

  it("logs in and routes to dashboard when no password change is required", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/v1/auth/login", () => HttpResponse.json({ id: "u", role: "member", must_change_password: false })),
      http.get("/v1/auth/me", () => HttpResponse.json(ME())),
    );
    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText(/email/i), "d@x.io");
    await user.type(screen.getByLabelText(/password/i), "pw");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("/", { replace: true }));
  });

  it("forces a password change on first login", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/v1/auth/login", () => HttpResponse.json({ id: "u", role: "member", must_change_password: true })),
      http.get("/v1/auth/me", () => HttpResponse.json(ME({ must_change_password: true }))),
    );
    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText(/email/i), "d@x.io");
    await user.type(screen.getByLabelText(/password/i), "pw");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("/change-password", { replace: true }));
  });

  it("shows a generic error on bad credentials", async () => {
    const user = userEvent.setup();
    server.use(http.post("/v1/auth/login", () => HttpResponse.json({ error: { code: "unauthorized", message: "Invalid email or password" } }, { status: 401 })));
    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText(/email/i), "d@x.io");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/Invalid email or password/i)).toBeInTheDocument();
  });
});
