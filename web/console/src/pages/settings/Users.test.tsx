import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import Users from "./Users";

describe("Users", () => {
  it("lists users and invites a new one", async () => {
    server.use(http.get("/v1/users", () => HttpResponse.json({ users: [
      { id: "u1", name: "Davis L.", email: "d@x.io", role: "owner", status: "active" },
    ] })));
    let body: any = null;
    server.use(http.post("/v1/users", async ({ request }) => { body = await request.json(); return HttpResponse.json({ id: "u2", ...body, status: "active" }); }));
    renderWithProviders(<Users />);
    expect(await screen.findByText("Davis L.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Invite user/i }));
    await userEvent.type(screen.getByLabelText(/email/i), "maya@x.io");
    await userEvent.type(screen.getByLabelText(/name/i), "Maya R.");
    await userEvent.type(screen.getByLabelText(/password/i), "temp-pass");
    await userEvent.click(screen.getByRole("button", { name: /Send invite/i }));
    await waitFor(() => expect(body).toMatchObject({ email: "maya@x.io", name: "Maya R.", role: "member" }));
  });
});
