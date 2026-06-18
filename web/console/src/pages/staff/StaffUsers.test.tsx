import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import StaffUsers from "./StaffUsers";

const ME = {
  id: "usr_me", tenant_id: null, name: "Me", email: "me@x.io",
  role: "member", is_staff: true, must_change_password: false, tenant: null, tenants: [],
};

describe("StaffUsers", () => {
  it("lists staff and adds a new staff user", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(ME)));
    server.use(http.get("/admin/v1/staff", () => HttpResponse.json({ staff: [
      { id: "usr_me", name: "Me", email: "me@x.io", status: "active", must_change_password: false, created_at: "2026-01-01T00:00:00Z" },
    ] })));
    let body: unknown = null;
    server.use(http.post("/admin/v1/staff", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ id: "usr_new", is_staff: true }, { status: 201 });
    }));

    renderWithProviders(<StaffUsers />);

    expect(await screen.findByText("me@x.io")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add staff" }));
    await userEvent.type(screen.getByLabelText(/full name/i), "Ada L.");
    await userEvent.type(screen.getByLabelText(/email/i), "ada@x.io");
    await userEvent.type(screen.getByLabelText(/password/i), "temp-pass");
    await userEvent.click(screen.getByRole("button", { name: "Add staff user" }));

    await waitFor(() =>
      expect(body).toMatchObject({ email: "ada@x.io", name: "Ada L.", password: "temp-pass" }),
    );
  });

  it("deactivates another staff user but not yourself", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json(ME)));
    server.use(http.get("/admin/v1/staff", () => HttpResponse.json({ staff: [
      { id: "usr_me", name: "Me", email: "me@x.io", status: "active", must_change_password: false, created_at: "2026-01-01T00:00:00Z" },
      { id: "usr_other", name: "Other", email: "other@x.io", status: "active", must_change_password: false, created_at: "2026-01-02T00:00:00Z" },
    ] })));
    let patched: { id?: string; status?: string } = {};
    server.use(http.patch("/admin/v1/staff/:id", async ({ params, request }) => {
      patched = { id: params.id as string, ...(await request.json() as object) };
      return HttpResponse.json({ id: params.id, status: "disabled" });
    }));

    renderWithProviders(<StaffUsers />);
    await screen.findByText("other@x.io");

    const deactivate = screen.getAllByRole("button", { name: /deactivate/i });
    // Two rows -> two Deactivate buttons; the self row's is disabled.
    const selfBtn = deactivate.find((b) => (b as HTMLButtonElement).disabled);
    const otherBtn = deactivate.find((b) => !(b as HTMLButtonElement).disabled);
    expect(selfBtn).toBeTruthy();
    expect(otherBtn).toBeTruthy();

    await userEvent.click(otherBtn!);
    await waitFor(() => expect(patched).toMatchObject({ id: "usr_other", status: "disabled" }));
  });
});
