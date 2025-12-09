import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import Credentials from "./Credentials";

describe("Credentials", () => {
  it("shows provider + last-4 only, never a secret", async () => {
    server.use(http.get("/v1/credentials", () => HttpResponse.json({ credentials: [
      { id: "cred_1", provider: "anthropic", last4: "8f3a", created_by: "Davis", created_at: "t" },
    ] })));
    renderWithProviders(<Credentials />);
    expect(await screen.findByText(/8f3a/)).toBeInTheDocument();
    expect(screen.getAllByText("anthropic").length).toBeGreaterThan(0);
  });

  it("sets a credential by POSTing provider + api_key", async () => {
    server.use(http.get("/v1/credentials", () => HttpResponse.json({ credentials: [] })));
    let body: any = null;
    server.use(http.post("/v1/credentials", async ({ request }) => { body = await request.json(); return HttpResponse.json({ id: "cred_9", provider: body.provider, last4: "xxxx", created_by: "Davis", created_at: "t" }); }));
    renderWithProviders(<Credentials />);
    await userEvent.click(await screen.findByRole("button", { name: /Add API key/i }));
    await userEvent.type(await screen.findByLabelText(/API key/i), "sk-ant-secret");
    await userEvent.click(screen.getByRole("button", { name: /Save credential/i }));
    await waitFor(() => expect(body).toMatchObject({ provider: "anthropic", api_key: "sk-ant-secret" }));
  });

  it("shows auth method + status badges and an account tail for subscriptions", async () => {
    server.use(http.get("/v1/credentials", () => HttpResponse.json({ credentials: [
      { id: "cred_1", provider: "openai", auth_method: "oauth_subscription", status: "active",
        last4: null, account_tail: "5678", expires_at: "2026-06-04T12:00:00Z",
        created_by: "Davis", created_at: "t" },
    ] })));
    renderWithProviders(<Credentials />);
    expect(await screen.findByText(/5678/)).toBeInTheDocument();
    expect(screen.getAllByText(/subscription/i).length).toBeGreaterThan(0);
  });

  it("starts the ChatGPT device flow and shows the user code", async () => {
    server.use(http.get("/v1/credentials", () => HttpResponse.json({ credentials: [] })));
    server.use(http.post("/v1/credentials/oauth/openai/start", () => HttpResponse.json({
      connection_id: "oac_1", user_code: "ABCD-1234",
      verification_uri: "https://auth.openai.com/codex/device",
      verification_uri_complete: "https://auth.openai.com/codex/device?u=ABCD-1234",
      expires_in: 900, interval: 5,
    })));
    server.use(http.get("/v1/credentials/oauth/openai/connections/oac_1", () =>
      HttpResponse.json({ connection_id: "oac_1", status: "connected", error: null, credential_id: "cred_9" })));
    renderWithProviders(<Credentials />);
    await userEvent.click(await screen.findByRole("button", { name: /Connect ChatGPT/i }));
    expect(await screen.findByText("ABCD-1234")).toBeInTheDocument();
  });
});
