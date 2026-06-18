import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import StaffArea from "./StaffArea";

describe("StaffArea", () => {
  it("lists tenants and shows a health indicator", async () => {
    server.use(http.get("/admin/v1/tenants", () => HttpResponse.json({ tenants: [{ id: "tnt_1", name: "Acme", status: "active" }] })));
    server.use(http.get("/admin/v1/health", () => HttpResponse.json({ status: "ok", containers_running: 9 })));
    renderWithProviders(<StaffArea />);
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(await screen.findByText(/ok/i)).toBeInTheDocument();
  });
});
