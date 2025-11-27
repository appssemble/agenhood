import { useState } from "react";
import {
  useContainer, useFiles, useGitLink, useGitLinkKey, useLinkGitRepo,
  useRepullGitRepo, useUnlinkGitRepo, useVerifyGitLink,
} from "../api/queries";
import { ConfirmDialog } from "./ConfirmDialog";
import { useToast } from "./Toast";
import { ApiError } from "../api/client";
import { Button, Field, Pill, Dropdown } from "../ui";
import { Input } from "../ui/inputs";
import { Icons } from "../ui/Icon";
import { validateSshUrl, validateBranch } from "../lib/gitRemote";

/** Small rounded glyph tile, mirroring the Snapshots page header tiles. */
function Tile({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <div
      aria-hidden
      style={{
        width: 36, height: 36, borderRadius: 10, flex: "0 0 36px",
        display: "grid", placeItems: "center", color: "var(--ink)",
        background: accent ? "var(--p-300)" : "var(--surface-3)",
      }}
    >
      {children}
    </div>
  );
}

/**
 * GitLinkPanel — pull-mode "link a git repo" flow for a container's Files page.
 *
 * Snapshot mode: offers a "Link a Git repository" entry that reveals a deploy
 * key, a verify-the-remote step, a branch picker, and a destructive
 * confirm gate (only when the workspace already has files). The key is
 * provisioned into the workspace so the agent can push when granted write access.
 * Linked mode: shows the linked repo with Re-pull / Unlink actions.
 */
export function GitLinkPanel({ cid }: { cid: string }) {
  const container = useContainer(cid).data;
  const linked = container?.git_mode === "linked";
  const files = useFiles(cid).data?.files ?? [];
  const hasFiles = files.length > 0;
  const toast = useToast();

  const linkQ = useGitLink(cid, linked);
  const keyM = useGitLinkKey(cid);
  const verifyM = useVerifyGitLink(cid);
  const linkM = useLinkGitRepo(cid);
  const repullM = useRepullGitRepo(cid);
  const unlinkM = useUnlinkGitRepo(cid);

  const [open, setOpen] = useState(false);
  const [pub, setPub] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [branches, setBranches] = useState<string[] | null>(null);
  const [branch, setBranch] = useState("main");
  const [confirmed, setConfirmed] = useState(false);
  const [repullOpen, setRepullOpen] = useState(false);
  const [unlinkOpen, setUnlinkOpen] = useState(false);

  // ---- Linked mode card ---------------------------------------------------
  if (linked) {
    const repo = linkQ.data?.linked ?? null;
    return (
      <div className="card" style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <Tile accent><Icons.Code w={18} /></Tile>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <Pill tone="success">Linked</Pill>
              <span className="mono" style={{ fontSize: 13, fontWeight: 600, wordBreak: "break-all" }}>
                {repo?.url ?? "—"}
              </span>
              {repo?.branch && <span className="chip">{repo.branch}</span>}
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
              Snapshots are off — git is managed by the agent. Last pull:{" "}
              {repo?.last_clone_status ?? "—"}
              {repo?.last_clone_status === "failed" && repo?.last_clone_error
                ? ` · ${repo.last_clone_error}`
                : ""}.
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <Button
              variant="secondary" size="sm"
              disabled={repullM.isPending}
              onClick={() => setRepullOpen(true)}
            >
              <Icons.Refresh w={14} /> {repullM.isPending ? "Re-pulling…" : "Re-pull"}
            </Button>
            <Button variant="danger" size="sm" onClick={() => setUnlinkOpen(true)}>Unlink</Button>
          </div>
        </div>

        <ConfirmDialog
          open={repullOpen}
          title="Re-pull branch?"
          body={`This replaces all current workspace files with ${repo?.url ?? "the repo"} @ ${repo?.branch ?? "the branch"}. This can't be undone.`}
          confirmLabel="Re-pull"
          onConfirm={async () => {
            setRepullOpen(false);
            try { await repullM.mutateAsync(); toast.success("Re-pulled"); }
            catch (e) { toast.error("Re-pull failed", e instanceof ApiError ? e.message : undefined); }
          }}
          onCancel={() => setRepullOpen(false)}
        />
        <ConfirmDialog
          open={unlinkOpen}
          title="Unlink repo?"
          body="Files stay as they are and automatic snapshots resume."
          confirmLabel="Unlink"
          onConfirm={async () => {
            setUnlinkOpen(false);
            try { await unlinkM.mutateAsync(); toast.success("Unlinked"); }
            catch (e) { toast.error("Unlink failed", e instanceof ApiError ? e.message : undefined); }
          }}
          onCancel={() => setUnlinkOpen(false)}
        />
      </div>
    );
  }

  // ---- Snapshot mode: link entry + flow -----------------------------------
  async function openFlow() {
    setOpen(true);
    setConfirmed(false);
    try { const k = await keyM.mutateAsync(undefined); setPub(k.public_key); }
    catch (e) { toast.error("Could not get deploy key", e instanceof ApiError ? e.message : undefined); }
  }

  async function doVerify() {
    const urlErr = validateSshUrl(url);
    if (urlErr) { toast.error(urlErr); return; }
    try {
      const v = await verifyM.mutateAsync(url);
      if (!v.ok) { toast.error("Verify failed", "Could not reach the repository"); return; }
      setBranches(v.branches);
      setBranch(v.default_branch ?? v.branches[0] ?? "main");
    } catch (e) { toast.error("Verify failed", e instanceof ApiError ? e.message : undefined); }
  }

  async function doLink() {
    const bErr = validateBranch(branch);
    if (bErr) { toast.error(bErr); return; }
    try {
      await linkM.mutateAsync({ url, branch });
      toast.success("Repo linked");
      setOpen(false);
    } catch (e) { toast.error("Link failed", e instanceof ApiError ? e.message : undefined); }
  }

  if (!open) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Tile><Icons.Code w={18} /></Tile>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em" }}>Link a Git repository</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>
            Pull a repo into this workspace over SSH using a deploy key. The agent then manages
            git and automatic snapshots turn off — grant the key write access if you want the
            agent to push changes back.
          </div>
        </div>
        <Button variant="primary" size="sm" onClick={openFlow}>Link a Git repository</Button>
      </div>
    );
  }

  const canLink = !!branches && (!hasFiles || confirmed) && !linkM.isPending;

  return (
    <div className="card" style={{ display: "grid", gap: 16 }}>
      <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em" }}>Link a Git repository</div>

      <Field label="Deploy key — add this to your repository" htmlFor="gl-key">
        <pre
          id="gl-key"
          aria-label="Deploy key"
          style={{
            fontSize: 11, fontFamily: "monospace", background: "var(--surface-3)",
            borderRadius: 8, padding: "10px 12px", overflowX: "auto",
            whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0, maxHeight: 120,
          }}
        >
          {pub ?? "Generating key…"}
        </pre>
        {pub && (
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <Button
              variant="secondary" size="sm"
              onClick={() => { void navigator.clipboard.writeText(pub).then(() => toast.success("Copied")); }}
            >
              Copy
            </Button>
          </div>
        )}
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
          Read access is enough to pull. Grant <strong>write</strong> access if you want the
          agent to push changes back to the remote.
        </div>
      </Field>

      <Field label="Repository URL (SSH)" htmlFor="gl-url">
        <div style={{ display: "flex", gap: 8 }}>
          <Input
            id="gl-url"
            aria-label="Repository URL"
            value={url}
            onChange={(e) => { setUrl(e.target.value); setBranches(null); setConfirmed(false); }}
            placeholder="git@github.com:owner/repo.git"
          />
          <Button
            variant="secondary" size="sm"
            disabled={!url || verifyM.isPending}
            onClick={doVerify}
          >
            {verifyM.isPending ? "Verifying…" : "Verify"}
          </Button>
        </div>
      </Field>

      {branches && (
        <Field label="Branch" htmlFor="gl-branch">
          <Dropdown
            id="gl-branch"
            aria-label="Branch"
            value={branch}
            options={branches.map((b) => ({ value: b, label: b }))}
            onChange={setBranch}
          />
        </Field>
      )}

      {branches && hasFiles && (
        <label
          style={{
            display: "flex", alignItems: "flex-start", gap: 8,
            padding: "10px 12px", borderRadius: 8, fontSize: 12.5,
            background: "var(--err-50, #fef2f2)",
            border: "1px solid var(--err-border, #fca5a5)", color: "var(--ink-2)",
          }}
        >
          <input
            type="checkbox"
            aria-label="Confirm replacing workspace files"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            style={{ marginTop: 2 }}
          />
          <span>
            Linking <strong>replaces all current workspace files</strong> with {url || "the repo"} @ {branch}.
            This can't be undone.
          </span>
        </label>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <Button variant="primary" size="sm" onClick={doLink} disabled={!canLink}>
          {linkM.isPending ? "Linking…" : "Link & pull"}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}
