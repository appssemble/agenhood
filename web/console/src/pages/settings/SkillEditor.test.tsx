import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import SkillEditor from "./SkillEditor";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({}),            // no :id -> create mode
  useNavigate: () => navigate,
}));

describe("SkillEditor (create mode)", () => {
  it("POSTs a new inline skill and returns to the list", async () => {
    let created: any = null;
    server.use(
      http.post("/v1/skills", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json({ id: "skl_2", ...created, created_at: null, updated_at: null });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "lint");
    await userEvent.type(screen.getByLabelText("Description"), "Run linters");
    await userEvent.type(screen.getByLabelText("Instructions"), "# lint steps");
    await userEvent.click(screen.getByRole("button", { name: /save skill/i }));
    await waitFor(() => expect(created).toMatchObject({ name: "lint", description: "Run linters" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/skills"));
  });

  it("shows a validation hint for an invalid name", async () => {
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "Bad Name");
    expect(screen.getByText(/lowercase|a-z0-9|hyphen/i)).toBeInTheDocument();
  });

  it("renders a live SKILL.md preview from the entered fields", async () => {
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "lint");
    await userEvent.type(screen.getByLabelText("Description"), "Run linters");
    expect(screen.getByText(/name: lint/)).toBeInTheDocument();
  });
});

describe("SkillEditor (git source)", () => {
  it("normalizes pasted URLs and loads the branch combobox on blur", async () => {
    let asked: any = null;
    server.use(
      http.post("/v1/skills/git-refs", async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));

    const url = screen.getByLabelText("Repository URL");
    const ref = screen.getByLabelText("Ref");
    expect(ref).not.toBeDisabled();          // always editable — a SHA/tag can be typed any time

    // A pasted ssh URL is converted to https for public access, no error shown.
    await userEvent.type(url, "git@github.com:org/repo.git");
    await userEvent.tab();
    await waitFor(() => expect(asked).toMatchObject({ source_url: "https://github.com/org/repo" }));
    await waitFor(() => expect(ref).toHaveValue("main"));
    expect(document.querySelectorAll("#git-branches option")).toHaveLength(2);

    // Unparseable input shows the validation hint and does not query.
    asked = null;
    await userEvent.clear(url);
    await userEvent.type(url, "not a url");
    await userEvent.tab();
    expect(screen.getByRole("alert")).toHaveTextContent(/Enter a repository URL/i);
    expect(asked).toBeNull();
  });
});

describe("SkillEditor (repository access / deploy keys)", () => {
  const DEPLOY_KEY = {
    id: "dk_1", name: "team", ssh_public_key: "ssh-ed25519 AAAA test", key_type: "ed25519",
    key_fingerprint: "SHA256:abc123", created_at: null, updated_at: null,
  };

  async function selectDeployKey() {
    fireEvent.click(screen.getByRole("button", { name: "Private" }));
    fireEvent.click(screen.getByLabelText("Deploy key"));
    fireEvent.mouseDown(await screen.findByRole("option", { name: "team" }));
  }

  it("hides the deploy-key picker until Private is chosen", async () => {
    server.use(http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [DEPLOY_KEY] })));
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));

    expect(screen.queryByLabelText("Deploy key")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate new deploy key…" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Private" }));
    expect(screen.getByLabelText("Deploy key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate new deploy key…" })).toBeInTheDocument();
  });

  it("converts a pasted https URL to ssh when a key is selected", async () => {
    let asked: any = null;
    server.use(
      http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [DEPLOY_KEY] })),
      http.post("/v1/skills/git-refs", async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({ ok: true, branches: ["main"], default_branch: "main" });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));
    await selectDeployKey();

    const url = screen.getByLabelText("Repository URL");
    await userEvent.type(url, "https://github.com/org/repo");
    await userEvent.tab();

    // No wrong-scheme error; the converted target is shown and used for git-refs.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("git@github.com:org/repo.git")).toBeInTheDocument();
    await waitFor(() =>
      expect(asked).toMatchObject({ source_url: "git@github.com:org/repo.git", deploy_key_id: "dk_1" }),
    );
  });

  it("suggests attaching a deploy key when a public fetch hits auth_failed", async () => {
    server.use(
      http.post("/v1/skills/git-refs", () =>
        HttpResponse.json(
          { error: { code: "skill_refs_error", message: "auth_failed: permission denied" } },
          { status: 502 },
        ),
      ),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));

    const url = screen.getByLabelText("Repository URL");
    await userEvent.type(url, "https://github.com/org/private-repo");
    await userEvent.tab();

    expect(await screen.findByText(/looks private/i)).toBeInTheDocument();

    // The note's action switches access to Private and reveals the key picker.
    await userEvent.click(screen.getByRole("button", { name: "Use a deploy key" }));
    expect(screen.getByLabelText("Deploy key")).toBeInTheDocument();
  });

  it("sends deploy_key_id with the git-refs request", async () => {
    let asked: any = null;
    server.use(
      http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [DEPLOY_KEY] })),
      http.post("/v1/skills/git-refs", async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({ ok: true, branches: ["main"], default_branch: "main" });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));
    await selectDeployKey();

    const url = screen.getByLabelText("Repository URL");
    await userEvent.type(url, "git@github.com:org/repo.git");
    await userEvent.tab();

    await waitFor(() =>
      expect(asked).toMatchObject({ source_url: "git@github.com:org/repo.git", deploy_key_id: "dk_1" }),
    );
  });

  it("shows the auth_failed install hint with the selected key's public key", async () => {
    server.use(
      http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [DEPLOY_KEY] })),
      http.post("/v1/skills/git-refs", () =>
        HttpResponse.json(
          { error: { code: "skill_refs_error", message: "auth_failed: permission denied" } },
          { status: 502 },
        ),
      ),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));
    await selectDeployKey();

    const url = screen.getByLabelText("Repository URL");
    await userEvent.type(url, "git@github.com:org/repo.git");
    await userEvent.tab();

    expect(await screen.findByText(/isn't installed on this repo yet/i)).toBeInTheDocument();
    expect(await screen.findByText("ssh-ed25519 AAAA test")).toBeInTheDocument();
  });

  it("clears generated-key instructions when repository access changes", async () => {
    const NEW_KEY = {
      id: "dk_2", name: "new-key", ssh_public_key: "ssh-ed25519 BBBB new", key_type: "ed25519",
      key_fingerprint: "SHA256:def456", created_at: null, updated_at: null,
    };
    server.use(
      http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [DEPLOY_KEY] })),
      http.post("/v1/deploy-keys", async ({ request }) => {
        const body = await request.json();
        return HttpResponse.json({ ...NEW_KEY, name: (body as any).name });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));

    // Generate a new key - instruction box appears
    fireEvent.click(screen.getByRole("button", { name: "Private" }));
    await userEvent.click(screen.getByRole("button", { name: "Generate new deploy key…" }));
    await userEvent.type(screen.getByLabelText("New deploy key name"), "new-key");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));

    expect(await screen.findByText(/Key "new-key" created/i)).toBeInTheDocument();
    expect(screen.getByText("ssh-ed25519 BBBB new")).toBeInTheDocument();

    // Switching back to Public hides the picker and the instruction box.
    fireEvent.click(screen.getByRole("button", { name: "Public" }));

    expect(screen.queryByText(/Key "new-key" created/i)).not.toBeInTheDocument();
    expect(screen.queryByText("ssh-ed25519 BBBB new")).not.toBeInTheDocument();
  });
});
