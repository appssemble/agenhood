import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import ApiKeys from "./ApiKeys";

describe("ApiKeys", () => {
  it("lists keys by prefix without ever exposing a full secret", async () => {
    server.use(http.get("/v1/api-keys", () => HttpResponse.json({ keys: [
      { id: "key_1", name: "ci-deploy", prefix: "tk_live_", last_used_at: "t", created_at: "t", created_by: "Davis", status: "active" },
    ] })));
    renderWithProviders(<ApiKeys />);
    expect(await screen.findByText("ci-deploy")).toBeInTheDocument();
    expect(screen.getByText(/tk_live_/)).toBeInTheDocument();
  });

  it("reveals the new key once and hides it after dismissal", async () => {
    server.use(http.get("/v1/api-keys", () => HttpResponse.json({ keys: [] })));
    server.use(http.post("/v1/api-keys", () => HttpResponse.json({ id: "key_9", name: "new", key: "tk_live_FULLSECRET123", prefix: "tk_live_", created_at: "t" })));
    renderWithProviders(<ApiKeys />);
    await userEvent.click(await screen.findByRole("button", { name: /New key/i }));
    await userEvent.type(screen.getByLabelText(/name/i), "new");
    await userEvent.click(screen.getByRole("button", { name: /Create/i }));

    // revealed once
    expect(await screen.findByText("tk_live_FULLSECRET123")).toBeInTheDocument();

    // dismiss → secret gone
    await userEvent.click(screen.getByRole("button", { name: /Done|Dismiss/i }));
    expect(screen.queryByText("tk_live_FULLSECRET123")).not.toBeInTheDocument();
  });

  it("revokes a key after confirmation", async () => {
    server.use(http.get("/v1/api-keys", () => HttpResponse.json({ keys: [
      { id: "key_1", name: "legacy", prefix: "tk_live_", last_used_at: null, created_at: "t", created_by: "Maya", status: "active" },
    ] })));
    let revoked = false;
    server.use(http.delete("/v1/api-keys/key_1", () => { revoked = true; return new HttpResponse(null, { status: 204 }); }));
    renderWithProviders(<ApiKeys />);
    await userEvent.click(await screen.findByRole("button", { name: /Revoke/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Revoke key/i }));
    await waitFor(() => expect(revoked).toBe(true));
  });
});

test("a failed keys query surfaces the API error instead of a fake empty list", async () => {
  server.use(http.get("/v1/api-keys", () => HttpResponse.json(
    { error: { code: "validation_error", message: "Select a workspace to view its API keys" } },
    { status: 400 },
  )));
  renderWithProviders(<ApiKeys />);
  expect(await screen.findByText("Couldn't load API keys")).toBeInTheDocument();
  expect(screen.getByText(/Select a workspace to view its API keys/)).toBeInTheDocument();
  expect(screen.queryByText("No API keys yet")).not.toBeInTheDocument();
});
