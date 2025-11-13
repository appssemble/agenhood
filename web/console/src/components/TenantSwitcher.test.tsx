import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { AuthProvider } from "../auth/AuthProvider";
import { TenantSwitcher } from "./TenantSwitcher";

const MEMBER_ME = {
  id: "usr_1", tenant_id: "ten_a", name: "Ada", email: "ada@x.io", role: "owner",
  is_staff: false, must_change_password: false,
  tenant: { id: "ten_a", name: "Acme", limits: {} },
  active_tenant_id: "ten_a",
  tenants: [
    { id: "ten_a", name: "Acme", role: "owner" },
    { id: "ten_b", name: "Globex", role: "member" },
  ],
};

const STAFF_ME = {
  id: "usr_s", tenant_id: null, name: "Ops", email: "ops@x.io", role: "owner",
  is_staff: true, must_change_password: false, tenant: null,
  active_tenant_id: null, tenants: [],
};

describe("TenantSwitcher", () => {
  it("member: lists their tenants in the menu", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(MEMBER_ME)));
    renderWithProviders(<AuthProvider><TenantSwitcher /></AuthProvider>);
    expect(await screen.findByRole("button", { name: /Acme/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Acme/ }));
    expect(screen.getByText("Globex")).toBeInTheDocument();
  });

  it("staff: lists all tenants from the admin endpoint under 'All workspaces'", async () => {
    server.use(
      http.get("/v1/auth/me", () => HttpResponse.json(STAFF_ME)),
      http.get("/admin/v1/tenants", () => HttpResponse.json({
        tenants: [{ id: "ten_a", name: "Acme" }, { id: "ten_b", name: "Globex" }],
      })),
    );
    renderWithProviders(<AuthProvider><TenantSwitcher /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button"));
    expect(await screen.findByText("All workspaces")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    // No cross-tenant escape hatch anymore.
    expect(screen.queryByText(/Exit to all tenants/i)).not.toBeInTheDocument();
  });

  it("staff: shows '+ New workspace' which opens the create dialog", async () => {
    server.use(
      http.get("/v1/auth/me", () => HttpResponse.json(STAFF_ME)),
      http.get("/admin/v1/tenants", () => HttpResponse.json({ tenants: [{ id: "ten_a", name: "Acme" }] })),
    );
    renderWithProviders(<AuthProvider><TenantSwitcher /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button"));
    await userEvent.click(screen.getByText("New workspace"));
    expect(await screen.findByRole("dialog", { name: "New workspace" })).toBeInTheDocument();
  });

  it("staff with owned workspaces: groups 'Your workspaces' (owner badge) and 'All workspaces'", async () => {
    const STAFF_OWNER_ME = {
      ...STAFF_ME,
      tenants: [{ id: "ten_own", name: "My WS", role: "owner" }],
    };
    server.use(
      http.get("/v1/auth/me", () => HttpResponse.json(STAFF_OWNER_ME)),
      http.get("/admin/v1/tenants", () => HttpResponse.json({
        tenants: [{ id: "ten_own", name: "My WS" }, { id: "ten_other", name: "Other Co" }],
      })),
    );
    renderWithProviders(<AuthProvider><TenantSwitcher /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button"));
    // Owned workspace appears under "Your workspaces" with an owner badge…
    expect(await screen.findByText("Your workspaces")).toBeInTheDocument();
    expect(screen.getByText("My WS")).toBeInTheDocument();
    expect(screen.getByText("owner")).toBeInTheDocument();
    // …and the non-owned tenant appears under "All workspaces" (owned one not duplicated).
    expect(screen.getByText("All workspaces")).toBeInTheDocument();
    expect(screen.getByText("Other Co")).toBeInTheDocument();
  });

  it("member: shows '+ New workspace' which opens the create dialog", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(MEMBER_ME)));
    renderWithProviders(<AuthProvider><TenantSwitcher /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /Acme/ }));
    await userEvent.click(screen.getByText("New workspace"));
    expect(await screen.findByRole("dialog", { name: "New workspace" })).toBeInTheDocument();
  });
});
