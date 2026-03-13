import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "../components/Toast";
import { server } from "../test/server";
import Snapshots from "./Snapshots";

const SNAPSHOTS = [
  { sha: "a".repeat(40), ts: 1765500000, message: "task tsk_9: completed", task_id: "tsk_9", files_changed: 3 },
  { sha: "b".repeat(40), ts: 1765400000, message: "initial snapshot", task_id: null, files_changed: 0 },
];

/** A realistic SSH-style GitRemote fixture */
const SSH_REMOTE_BASE = {
  url: "git@github.com:acme/ws.git",
  branch: "main",
  ssh_public_key: "ssh-ed25519 AAAAB3NzaC1lZDI1NTE5AAAA",
  key_fingerprint: "SHA256:abc123",
  key_type: "ed25519",
  enabled: true,
  verified_at: "2025-01-01T00:00:00Z",
  needs_relink: false,
  last_push_status: null,
  last_push_error: null,
  last_push_at: null,
};

function mockApi(remote: object | null = null, containerStatus = "running") {
  server.use(
    http.get("/v1/containers/ctr_1", () =>
      HttpResponse.json({ id: "ctr_1", status: containerStatus, name: "test" }),
    ),
    http.get("/v1/containers/ctr_1/git/snapshots", () => HttpResponse.json({ snapshots: SNAPSHOTS })),
    http.get("/v1/containers/ctr_1/git/remote", () => HttpResponse.json({ remote })),
    http.get("/v1/containers/ctr_1/tasks", () => HttpResponse.json({ tasks: [] })),
  );
}

/** Stub the deploy-key gen endpoint (called when the link/edit form opens). */
function mockKeyGen(publicKey = "ssh-ed25519 AAAA_MOCK_KEY") {
  server.use(
    http.post("/v1/containers/ctr_1/git/remote/key", () =>
      HttpResponse.json({ public_key: publicKey, fingerprint: "SHA256:mock42", key_type: "ed25519" }),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/containers/ctr_1/snapshots"]}>
          <Routes>
            <Route path="/containers/:cid/snapshots" element={<Snapshots />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("Snapshots page", () => {
  it("renders the snapshot timeline", async () => {
    mockApi();
    renderPage();
    await waitFor(() => expect(screen.getByText("task tsk_9: completed")).toBeInTheDocument());
    expect(screen.getByText("aaaaaaa")).toBeInTheDocument();        // short sha
    expect(screen.getByText("initial snapshot")).toBeInTheDocument();
  });

  it("asks for confirmation before rolling back", async () => {
    mockApi();
    let rolledBack = false;
    server.use(
      http.post("/v1/containers/ctr_1/git/rollback", () => {
        rolledBack = true;
        return HttpResponse.json({ sha: "c".repeat(40) });
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("task tsk_9: completed")).toBeInTheDocument());
    const rowButtons = screen.getAllByRole("button", { name: /^Roll back$/ });
    await userEvent.click(rowButtons[0]);
    expect(rolledBack).toBe(false);                                  // dialog first
    // The dialog confirm button is also labeled "Roll back" — it is the last
    // one rendered (the dialog mounts after the rows).
    const allButtons = screen.getAllByRole("button", { name: /^Roll back$/ });
    await userEvent.click(allButtons[allButtons.length - 1]);
    await waitFor(() => expect(rolledBack).toBe(true));
  });

  it("shows the link-remote form when no remote is linked", async () => {
    mockApi(null);
    mockKeyGen();
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Link remote" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Link remote" }));
    expect(screen.getByPlaceholderText("git@github.com:you/repo.git")).toBeInTheDocument();
  });

  it("shows last push status for a linked remote", async () => {
    mockApi({
      ...SSH_REMOTE_BASE,
      url: "git@github.com:acme/ws.git",
      key_fingerprint: "SHA256:abc123",
      enabled: true,
      last_push_status: "failed",
      last_push_error: "push_auth_failed",
      last_push_at: "2026-06-12T10:00:00Z",
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("git@github.com:acme/ws.git")).toBeInTheDocument());
    expect(screen.getByText(/push_auth_failed/)).toBeInTheDocument();
    // Fingerprint tail: last 6 chars of "SHA256:abc123" = "abc123" → "••abc123"
    expect(screen.getByText(/key ••abc123/)).toBeInTheDocument();
  });

  it("toggles auto-push off from the linked remote card without resending the token", async () => {
    const remote = {
      ...SSH_REMOTE_BASE,
      enabled: true,
    };
    mockApi(remote);
    let putBody: Record<string, unknown> | null = null;
    server.use(
      http.put("/v1/containers/ctr_1/git/remote", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        putBody = body;
        return HttpResponse.json({ remote: { ...remote, enabled: body.enabled } });
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch", { name: "Auto-push" })).toBeInTheDocument());
    expect(screen.getByRole("switch", { name: "Auto-push" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("switch", { name: "Auto-push" }));
    await waitFor(() => expect(putBody).not.toBeNull());
    // No token key: the stored credential must be kept, and enabled flips to false.
    expect(putBody).toEqual({ url: remote.url, branch: remote.branch, enabled: false });
  });

  it("keeps a disabled remote disabled when edited through the form", async () => {
    const remote = {
      ...SSH_REMOTE_BASE,
      url: "git@github.com:acme/ws.git",
      branch: "main",
      enabled: false,
      verified_at: "2025-01-01T00:00:00Z",
    };
    mockApi(remote);
    mockKeyGen();
    let putBody: Record<string, unknown> | null = null;
    server.use(
      http.put("/v1/containers/ctr_1/git/remote", async ({ request }) => {
        putBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ remote: { ...remote, enabled: putBody.enabled } });
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch", { name: "Auto-push" })).toBeInTheDocument());
    expect(screen.getByRole("switch", { name: "Auto-push" })).toHaveAttribute("aria-checked", "false");
    // Edit is enabled because container is "running" (default).
    // Since verified_at is set, verifyState initializes to "ok" so Save is immediately enabled.
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    // The server defaults `enabled` to true, so the console must send the
    // current value or a disabled remote is silently re-enabled on every edit.
    await waitFor(() => expect(putBody).not.toBeNull());
    expect((putBody as unknown as Record<string, unknown>).enabled).toBe(false);
  });

  // ---- New tests: running-state gating ------------------------------------

  it("disables Link remote button and shows hint when container is not running", async () => {
    mockApi(null, "paused");
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Link remote" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Link remote" })).toBeDisabled();
    expect(screen.getByText(/Start the container to link a remote/)).toBeInTheDocument();
  });

  // ---- New tests: verify → branches + save-gating -------------------------

  it("shows deploy key after opening form and gates Save on verify", async () => {
    const MOCK_KEY = "ssh-ed25519 AAAAB3NzaC1lZDI1NTE5_TESTKEY";
    mockApi(null); // no remote, running container (default)
    mockKeyGen(MOCK_KEY);
    server.use(
      http.post("/v1/containers/ctr_1/git/remote/verify", () =>
        HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" }),
      ),
    );

    renderPage();

    // Open the form
    await waitFor(() => expect(screen.getByRole("button", { name: "Link remote" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Link remote" }));

    // Deploy key should appear once the key-gen mutation resolves
    await waitFor(() => expect(screen.getByText(MOCK_KEY)).toBeInTheDocument());

    // Save is disabled: verifyState is still "idle"
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    // Verify button is disabled while URL is invalid (empty)
    expect(screen.getByRole("button", { name: "Verify" })).toBeDisabled();

    // Type a valid SSH URL
    await userEvent.type(screen.getByLabelText("Repository URL"), "git@github.com:acme/repo.git");

    // Now Verify button should be enabled
    await waitFor(() => expect(screen.getByRole("button", { name: "Verify" })).not.toBeDisabled());

    // Click Verify manually (avoids relying on 600ms auto-debounce timer in tests)
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));

    // After verify resolves: status shows connected, branch datalist is populated
    await waitFor(() =>
      expect(screen.getByText(/connected · 2 branches/)).toBeInTheDocument()
    );

    // Branch datalist should have both options
    expect(document.querySelector("#rmt-branches option[value=\"main\"]")).toBeInTheDocument();
    expect(document.querySelector("#rmt-branches option[value=\"dev\"]")).toBeInTheDocument();

    // Save should now be enabled (verifyState = "ok", valid URL, valid branch)
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();
  });

  it("shows branch inline error and keeps Save disabled when branch is invalid after verify", async () => {
    const MOCK_KEY = "ssh-ed25519 AAAAB3NzaC1lZDI1NTE5_TESTKEY2";
    mockApi(null);
    mockKeyGen(MOCK_KEY);
    server.use(
      http.post("/v1/containers/ctr_1/git/remote/verify", () =>
        HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" }),
      ),
    );

    renderPage();

    await waitFor(() => expect(screen.getByRole("button", { name: "Link remote" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Link remote" }));

    await waitFor(() => expect(screen.getByText(MOCK_KEY)).toBeInTheDocument());

    // Type a valid URL and verify
    await userEvent.type(screen.getByLabelText("Repository URL"), "git@github.com:acme/repo.git");
    await waitFor(() => expect(screen.getByRole("button", { name: "Verify" })).not.toBeDisabled());
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(screen.getByText(/connected · 2 branches/)).toBeInTheDocument());

    // Save is enabled at this point (branch is "main", valid)
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();

    // Clear the branch field and type an invalid branch name
    const branchInput = screen.getByLabelText("Branch");
    await userEvent.clear(branchInput);
    await userEvent.type(branchInput, "a..b");

    // Inline branch error should appear
    await waitFor(() =>
      expect(screen.getByText("Invalid branch name")).toBeInTheDocument(),
    );

    // Save must remain disabled due to the invalid branch
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("adopts default_branch from verify response when branch is still the 'main' placeholder", async () => {
    const MOCK_KEY = "ssh-ed25519 AAAAB3NzaC1lZDI1NTE5_TESTKEY3";
    mockApi(null);
    mockKeyGen(MOCK_KEY);
    server.use(
      http.post("/v1/containers/ctr_1/git/remote/verify", () =>
        HttpResponse.json({ ok: true, branches: ["develop", "main"], default_branch: "develop" }),
      ),
    );

    renderPage();

    await waitFor(() => expect(screen.getByRole("button", { name: "Link remote" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Link remote" }));

    await waitFor(() => expect(screen.getByText(MOCK_KEY)).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText("Repository URL"), "git@github.com:acme/repo.git");
    await waitFor(() => expect(screen.getByRole("button", { name: "Verify" })).not.toBeDisabled());
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(screen.getByText(/connected/)).toBeInTheDocument());

    // Branch input should now show "develop" (the remote's default_branch)
    const branchInput = screen.getByLabelText("Branch") as HTMLInputElement;
    expect(branchInput.value).toBe("develop");
  });

  // ---- Linked (pull) mode: snapshots disabled -----------------------------

  it("shows the disabled explanation when the workspace is linked to a git repo", async () => {
    server.use(
      http.get("/v1/containers/ctr_1", () =>
        HttpResponse.json({ id: "ctr_1", status: "running", name: "test", git_mode: "linked" }),
      ),
      http.get("/v1/containers/ctr_1/git/snapshots", () =>
        HttpResponse.json({
          snapshots: [],
          disabled: true,
          linked: { url: "git@h:o/r.git", branch: "main" },
        }),
      ),
      http.get("/v1/containers/ctr_1/git/remote", () => HttpResponse.json({ remote: null })),
      http.get("/v1/containers/ctr_1/tasks", () => HttpResponse.json({ tasks: [] })),
    );

    renderPage();

    // Disabled copy renders and names the linked repo + branch
    await waitFor(() => expect(screen.getByText("Snapshots are off")).toBeInTheDocument());
    expect(screen.getByText("git@h:o/r.git")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();

    // Links to the Files page where the link is managed
    expect(screen.getByRole("link", { name: /Files/i })).toHaveAttribute(
      "href",
      "/containers/ctr_1/files",
    );

    // The rollback timeline and the push-remote form must NOT render while linked
    expect(screen.queryByText("Restore points")).not.toBeInTheDocument();
    expect(screen.queryByText("Backup remote")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Link remote" })).not.toBeInTheDocument();
  });
});
