import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import DeployKeys from "./DeployKeys";

// Fixtures never include private-key material — the API never sends it.
const DEPLOY_KEYS = [
  {
    id: "dk_1",
    name: "team",
    ssh_public_key: "ssh-ed25519 AAAA test",
    key_type: "ed25519",
    key_fingerprint: "SHA256:abc123",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

describe("DeployKeys settings page", () => {
  it("lists the tenant's deploy keys by fingerprint, never a private key", async () => {
    server.use(http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: DEPLOY_KEYS })));
    renderWithProviders(<DeployKeys />);
    expect(await screen.findByText("team")).toBeInTheDocument();
    expect(screen.getByText(/SHA256:abc123/)).toBeInTheDocument();
  });

  it("creates a key and shows only the public half", async () => {
    server.use(http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [] })));
    let body: any = null;
    server.use(
      http.post("/v1/deploy-keys", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          {
            id: "dk_1",
            name: body.name,
            ssh_public_key: "ssh-ed25519 AAAA test",
            key_type: "ed25519",
            key_fingerprint: "SHA256:abc123",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );
    renderWithProviders(<DeployKeys />);
    await userEvent.click(await screen.findByRole("button", { name: /Generate key/i }));
    await userEvent.type(screen.getByLabelText(/name/i), "team");
    await userEvent.click(screen.getByRole("button", { name: /^Generate key$/i }));

    await waitFor(() => expect(body).toMatchObject({ name: "team" }));
    expect(await screen.findByText("ssh-ed25519 AAAA test")).toBeInTheDocument();
    expect(screen.getByText(/SHA256:abc123/)).toBeInTheDocument();
    expect(screen.getByText(/Deploy keys.*Add deploy key/i)).toBeInTheDocument();
    expect(screen.getByText(/Allow write access.*unchecked/i)).toBeInTheDocument();
  });

  it("delete in use renders the dependent skills message", async () => {
    server.use(http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: DEPLOY_KEYS })));
    server.use(
      http.delete("/v1/deploy-keys/dk_1", () =>
        HttpResponse.json(
          { error: { code: "deploy_key_in_use", message: "deploy key is used by skill(s): a, b" } },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<DeployKeys />);
    await userEvent.click(await screen.findByRole("button", { name: /Delete/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Delete key/i }));
    expect(await screen.findByText(/deploy key is used by skill\(s\): a, b/i)).toBeInTheDocument();
  });

  it("deletes a key after confirmation", async () => {
    server.use(http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: DEPLOY_KEYS })));
    let deleted = false;
    server.use(
      http.delete("/v1/deploy-keys/dk_1", () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    renderWithProviders(<DeployKeys />);
    await userEvent.click(await screen.findByRole("button", { name: /Delete/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Delete key/i }));
    await waitFor(() => expect(deleted).toBe(true));
  });
});
