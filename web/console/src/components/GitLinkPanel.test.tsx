import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, beforeEach, test, expect } from "vitest";
import { GitLinkPanel } from "./GitLinkPanel";

// Mutable per-test state, referenced by the hoisted query mocks.
const state = vi.hoisted(() => ({
  git_mode: "snapshot" as "snapshot" | "linked",
  files: [] as Array<{ name: string }>,
  linked: null as Record<string, unknown> | null,
  keyResult: { public_key: "ssh-ed25519 AAAADEPLOYKEY user@host", fingerprint: "ab:cd", key_type: "ed25519" },
  verifyResult: { ok: true, branches: ["main", "dev"], default_branch: "dev" } as {
    ok: boolean; branches: string[]; default_branch: string | null;
  },
}));

const keyMutate = vi.fn(async () => state.keyResult);
const verifyMutate = vi.fn(async () => state.verifyResult);
const linkMutate = vi.fn(async () => ({ linked: {} }));
const repullMutate = vi.fn(async () => ({ linked: {} }));
const unlinkMutate = vi.fn(async () => ({}));

vi.mock("../api/queries", () => ({
  useContainer: () => ({ data: { git_mode: state.git_mode, status: "running" } }),
  useFiles: () => ({ data: { files: state.files } }),
  useGitLink: () => ({ data: { linked: state.linked } }),
  useGitLinkKey: () => ({ mutateAsync: keyMutate, isPending: false }),
  useVerifyGitLink: () => ({ mutateAsync: verifyMutate, isPending: false }),
  useLinkGitRepo: () => ({ mutateAsync: linkMutate, isPending: false }),
  useRepullGitRepo: () => ({ mutateAsync: repullMutate, isPending: false }),
  useUnlinkGitRepo: () => ({ mutateAsync: unlinkMutate, isPending: false }),
}));

vi.mock("./Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

beforeEach(() => {
  state.git_mode = "snapshot";
  state.files = [];
  state.linked = null;
  state.verifyResult = { ok: true, branches: ["main", "dev"], default_branch: "dev" };
  keyMutate.mockClear();
  verifyMutate.mockClear();
  linkMutate.mockClear();
  repullMutate.mockClear();
  unlinkMutate.mockClear();
});

const VALID_URL = "git@github.com:owner/repo.git";

async function openFlowAndVerify() {
  fireEvent.click(screen.getByRole("button", { name: /link a git repository/i }));
  fireEvent.change(screen.getByLabelText(/repository url/i), { target: { value: VALID_URL } });
  fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));
  await waitFor(() => expect(verifyMutate).toHaveBeenCalledWith(VALID_URL));
}

test("snapshot mode, no files: link entry opens the flow and shows the deploy key", async () => {
  render(<GitLinkPanel cid="ctr_1" />);
  fireEvent.click(screen.getByRole("button", { name: /link a git repository/i }));
  await waitFor(() => expect(keyMutate).toHaveBeenCalled());
  const key = await screen.findByLabelText(/deploy key/i);
  expect(key.textContent).toContain("AAAADEPLOYKEY");
});

test("verify populates the branch dropdown defaulting to default_branch", async () => {
  render(<GitLinkPanel cid="ctr_1" />);
  await openFlowAndVerify();
  // The branch Dropdown trigger (a button labelled "Branch") shows the
  // selected option label, which defaults to default_branch = "dev".
  const trigger = await screen.findByRole("button", { name: /^branch$/i });
  expect(trigger).toHaveTextContent("dev");
});

test("destructive warning gates Link when the workspace has files", async () => {
  state.files = [{ name: "README.md" }];
  render(<GitLinkPanel cid="ctr_1" />);
  await openFlowAndVerify();

  expect(await screen.findByText(/replaces all current workspace files/i)).toBeInTheDocument();
  const linkBtn = screen.getByRole("button", { name: /link & pull/i });
  expect(linkBtn).toBeDisabled();

  fireEvent.click(screen.getByLabelText(/confirm replacing workspace files/i));
  await waitFor(() => expect(linkBtn).not.toBeDisabled());
});

test("no warning and Link enabled immediately when the workspace is empty", async () => {
  state.files = [];
  render(<GitLinkPanel cid="ctr_1" />);
  await openFlowAndVerify();

  expect(screen.queryByText(/replaces all current workspace files/i)).not.toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /link & pull/i })).not.toBeDisabled(),
  );
});

test("linked mode renders the linked card with Re-pull and Unlink actions", () => {
  state.git_mode = "linked";
  state.linked = {
    url: "git@github.com:owner/repo.git",
    branch: "main",
    last_clone_status: "cloned",
    last_clone_error: null,
  };
  render(<GitLinkPanel cid="ctr_1" />);

  expect(screen.getByText("Linked")).toBeInTheDocument();
  expect(screen.getByText("git@github.com:owner/repo.git")).toBeInTheDocument();
  expect(screen.getByText("main")).toBeInTheDocument();
  expect(screen.getByText(/snapshots are off/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /re-pull/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /unlink/i })).toBeInTheDocument();
});
