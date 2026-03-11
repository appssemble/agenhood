import { useState, useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useContainer, useGitPushNow, useGitRemote, useGitRemoteKey, useGitRollback,
  useGitSnapshots, useSaveGitRemote, useUnlinkGitRemote, useVerifyGitRemote,
} from "../api/queries";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import { Button, Field, Pill, Switch, EmptyState } from "../ui";
import { Input } from "../ui/inputs";
import { Icons } from "../ui/Icon";
import type { GitRemote, GitSnapshot } from "../api/types";
import { validateSshUrl, validateBranch } from "../lib/gitRemote";

const shortSha = (sha: string) => sha.slice(0, 7);

/** Derive a deploy-keys settings URL from an SSH remote URL. */
function deployKeysUrl(rawUrl: string): string | null {
  if (!rawUrl) return null;
  let host = "";
  let ownerRepo = "";

  // SCP form: git@host:owner/repo.git
  const scpMatch = rawUrl.match(/^[^@]+@([^:]+):(.+)$/);
  if (scpMatch) {
    host = scpMatch[1];
    ownerRepo = scpMatch[2].replace(/\.git$/, "");
  } else {
    // ssh:// form: ssh://git@host/owner/repo.git
    try {
      const u = new URL(rawUrl);
      if (u.protocol === "ssh:") {
        host = u.hostname;
        ownerRepo = u.pathname.replace(/^\//, "").replace(/\.git$/, "");
      }
    } catch {
      return null;
    }
  }

  if (!host) return null;
  if (!ownerRepo || !ownerRepo.includes("/")) return `https://${host}`;

  if (host === "github.com") return `https://github.com/${ownerRepo}/settings/keys`;
  if (host === "gitlab.com") return `https://gitlab.com/${ownerRepo}/-/settings/repository`;
  return `https://${host}`;
}

function relTime(ms: number): string {
  const diff = Date.now() - ms;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}
const relUnix = (ts: number) => relTime(ts * 1000);
const absUnix = (ts: number) => new Date(ts * 1000).toLocaleString();

/** Small rounded glyph tile used for section/section-card headers. */
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

type VerifyState = "idle" | "verifying" | "ok" | "error";

function RemoteCard({ cid, running }: { cid: string; running: boolean }) {
  const { data, isLoading } = useGitRemote(cid);
  const save = useSaveGitRemote(cid);
  const unlink = useUnlinkGitRemote(cid);
  const pushNow = useGitPushNow(cid);
  const remoteKey = useGitRemoteKey(cid);
  const verify = useVerifyGitRemote(cid);
  const toast = useToast();

  const [editing, setEditing] = useState(false);
  const [unlinkOpen, setUnlinkOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [urlDirty, setUrlDirty] = useState(false);
  const [verifyState, setVerifyState] = useState<VerifyState>("idle");
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [publicKey, setPublicKey] = useState("");

  // Stable ref so the debounce closure can read branch without being a dep
  const branchRef = useRef(branch);
  branchRef.current = branch;

  const remote: GitRemote | null = data?.remote ?? null;

  function openForm() {
    const existing = remote;
    setUrl(existing?.url ?? "");
    setBranch(existing?.branch ?? "main");
    setUrlDirty(false);
    setVerifyError(null);
    setBranches(existing?.branch ? [existing.branch] : []);
    setPublicKey(existing?.ssh_public_key ?? "");
    // If the remote was previously verified, start in ok state so Save is immediately available
    setVerifyState(existing?.verified_at ? "ok" : "idle");
    setEditing(true);
    remoteKey.mutate(undefined, {
      onSuccess: (d) => setPublicKey(d.public_key),
    });
  }

  // Auto-debounce verify: fires 600 ms after url changes (when urlDirty is set)
  useEffect(() => {
    if (!editing || !urlDirty || validateSshUrl(url) !== null || !publicKey) return;
    let cancelled = false;
    const id = setTimeout(async () => {
      if (cancelled) return;
      setVerifyState("verifying");
      setVerifyError(null);
      try {
        const result = await verify.mutateAsync(url);
        if (cancelled) return;
        if (result.ok) {
          setVerifyState("ok");
          setBranches(result.branches);
          if (result.default_branch && (branchRef.current === "" || branchRef.current === "main")) {
            setBranch(result.default_branch);
          }
        } else {
          setVerifyState("error");
          setVerifyError("Connection failed");
        }
      } catch (err) {
        if (cancelled) return;
        setVerifyState("error");
        setVerifyError(err instanceof ApiError ? err.message : "Verification failed");
      }
    }, 600);
    return () => { cancelled = true; clearTimeout(id); };
  }, [url, urlDirty, publicKey, editing]);

  async function onVerify() {
    setVerifyState("verifying");
    setVerifyError(null);
    try {
      const result = await verify.mutateAsync(url);
      if (result.ok) {
        setVerifyState("ok");
        setBranches(result.branches);
        if (result.default_branch && (branch === "" || branch === "main")) {
          setBranch(result.default_branch);
        }
      } else {
        setVerifyState("error");
        setVerifyError("Connection failed");
      }
    } catch (err) {
      setVerifyState("error");
      setVerifyError(err instanceof ApiError ? err.message : "Verification failed");
    }
  }

  async function onSave() {
    try {
      // Preserve the auto-push setting on edits — the server defaults
      // `enabled` to true, which would silently re-enable a disabled remote.
      await save.mutateAsync({ url, branch, enabled: remote?.enabled ?? true });
      setEditing(false);
      toast.success("Remote linked");
    } catch (err) {
      toast.error("Couldn't link remote", err instanceof ApiError ? err.message : undefined);
    }
  }

  const urlError = urlDirty && url ? validateSshUrl(url) : null;
  const canSave =
    verifyState === "ok" &&
    validateSshUrl(url) === null &&
    validateBranch(branch) === null;

  if (isLoading) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className="skel" style={{ width: 36, height: 36, borderRadius: 10 }} />
        <div style={{ display: "grid", gap: 6 }}>
          <span className="skel" style={{ width: 240, height: 12 }} />
          <span className="skel" style={{ width: 160, height: 10 }} />
        </div>
      </div>
    );
  }

  // ---- Empty (no remote) -------------------------------------------------
  if (!remote && !editing) {
    return (
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Tile><Icons.Code w={18} /></Tile>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em" }}>Backup remote</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>
            Restore points live in this workspace. Link a git remote to mirror its history (push-only, over SSH).
          </div>
          {!running && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
              Start the container to link a remote.
            </div>
          )}
        </div>
        <Button variant="primary" size="sm" disabled={!running} onClick={openForm}>
          Link remote
        </Button>
      </div>
    );
  }

  // ---- Edit / link form --------------------------------------------------
  if (editing) {
    const verifyIcon =
      verifyState === "ok" ? "✓"
        : verifyState === "error" ? "✗"
          : verifyState === "verifying" ? "◌"
            : "●";
    const verifyMsg =
      verifyState === "ok"
        ? `connected · ${branches.length} branch${branches.length === 1 ? "" : "es"}`
        : verifyState === "error"
          ? (verifyError ?? "failed")
          : verifyState === "verifying"
            ? "verifying…"
            : "not verified, add the key, then Verify";

    return (
      <div className="card" style={{ display: "grid", gap: 16 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em" }}>
          {remote ? "Edit remote" : "Link a remote"}
        </div>

        {/* Two-pane: flex-wrap collapses to one column on narrow viewports */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-start" }}>

          {/* Left pane: URL + Branch */}
          <div style={{ flex: "1 1 260px", minWidth: 0, display: "grid", gap: 12 }}>
            <Field label="Repository URL" htmlFor="rmt-url">
              <Input
                id="rmt-url"
                aria-label="Repository URL"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setUrlDirty(true);
                  setVerifyState("idle");
                }}
                placeholder="git@github.com:you/repo.git"
              />
              {urlError && (
                <div style={{ fontSize: 11.5, color: "var(--err-700)", marginTop: 4 }}>
                  {urlError}
                </div>
              )}
            </Field>
            <Field label="Branch" htmlFor="rmt-branch">
              <Input
                id="rmt-branch"
                aria-label="Branch"
                value={branch}
                list="rmt-branches"
                disabled={verifyState !== "ok"}
                onChange={(e) => setBranch(e.target.value)}
                placeholder="main"
              />
              <datalist id="rmt-branches">
                {branches.map((b) => <option key={b} value={b} />)}
              </datalist>
              {verifyState === "ok" && branch !== "" && validateBranch(branch) !== null && (
                <div style={{ fontSize: 11.5, color: "var(--err-700)", marginTop: 4 }}>
                  {validateBranch(branch)}
                </div>
              )}
            </Field>
          </div>

          {/* Right pane: Deploy key + status */}
          <div style={{ flex: "1 1 260px", minWidth: 0, display: "grid", gap: 10 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>Deploy key</div>
            {publicKey ? (
              <>
                <pre
                  aria-label="Deploy key"
                  style={{
                    fontSize: 11, fontFamily: "monospace", background: "var(--surface-3)",
                    borderRadius: 8, padding: "10px 12px", overflowX: "auto",
                    whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0, maxHeight: 120,
                  }}
                >
                  {publicKey}
                </pre>
                <div style={{ display: "flex", gap: 6 }}>
                  <Button
                    variant="secondary" size="sm"
                    onClick={() => {
                      void navigator.clipboard.writeText(publicKey).then(() => toast.success("Copied"));
                    }}
                  >
                    Copy
                  </Button>
                  <Button
                    variant="secondary" size="sm"
                    disabled={!running || remoteKey.isPending}
                    onClick={() => remoteKey.mutate(true, { onSuccess: (d) => setPublicKey(d.public_key) })}
                  >
                    Regenerate key
                  </Button>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                  Add this as a deploy key with <strong>write</strong> access to your repository.
                  {deployKeysUrl(url) && (
                    <>
                      {" "}
                      <a
                        href={deployKeysUrl(url)!}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: "var(--p-600, #7c3aed)" }}
                      >
                        Open deploy keys ↗
                      </a>
                    </>
                  )}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Generating key…</div>
            )}

            {/* Status panel */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              flexWrap: "wrap", gap: 8, padding: "8px 12px", borderRadius: 8,
              background: "var(--surface-3)", fontSize: 12.5,
            }}>
              <span style={{
                color: verifyState === "ok"
                  ? "var(--ok-700, #16a34a)"
                  : verifyState === "error"
                    ? "var(--err-700)"
                    : "var(--muted)",
              }}>
                {verifyIcon} {verifyMsg}
              </span>
              <Button
                variant="secondary" size="sm"
                disabled={verifyState === "verifying" || validateSshUrl(url) !== null || !publicKey}
                onClick={onVerify}
              >
                Verify
              </Button>
            </div>
          </div>
        </div>

        {/* Bottom row */}
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            variant="primary" size="sm"
            onClick={onSave}
            disabled={!canSave || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </div>
    );
  }

  // ---- Linked ------------------------------------------------------------
  const r = remote!;
  const fingerTail = r.key_fingerprint
    ? `••${r.key_fingerprint.slice(-6)}`
    : "no key";
  const statusPill =
    r.last_push_status === "pushed" ? <Pill tone="info">pushed</Pill>
      : r.last_push_status === "failed" ? <Pill tone="warn">push failed</Pill>
        : <Pill tone="dormant">never pushed</Pill>;

  return (
    <div className="card">
      {r.needs_relink && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexWrap: "wrap", gap: 10, padding: "8px 12px", marginBottom: 12,
          borderRadius: 8, background: "var(--warn-50, #fffbeb)",
          border: "1px solid var(--warn-border, #fcd34d)", fontSize: 13,
          color: "var(--ink-2)",
        }}>
          <span>Needs re-link. Backups now use SSH keys</span>
          <Button variant="primary" size="sm" disabled={!running} onClick={openForm}>
            Set up
          </Button>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <Tile><Icons.Code w={18} /></Tile>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 13, fontWeight: 600, wordBreak: "break-all" }}>{r.url}</span>
            <span className="chip">{r.branch}</span>
            {statusPill}
          </div>
          <div className="id" style={{ marginTop: 6, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span>key {fingerTail}</span>
            {r.last_push_status === "pushed" && r.last_push_at && (
              <span title={new Date(r.last_push_at).toLocaleString()}>
                pushed {relTime(new Date(r.last_push_at).getTime())}
              </span>
            )}
            {r.last_push_status === "failed" && (
              <span style={{ display: "inline-flex", gap: 6, alignItems: "center", color: "var(--err-700)" }}>
                <Icons.Warn w={13} /><span className="mono">{r.last_push_error ?? "failed"}</span>
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <Button
            variant="primary" size="sm"
            disabled={!running || pushNow.isPending}
            style={{ gap: 6, padding: "6px 10px" }}
            onClick={async () => {
              try { await pushNow.mutateAsync(); toast.success("Pushed"); }
              catch (err) { toast.error("Push failed", err instanceof ApiError ? err.message : undefined); }
            }}
          >
            <Icons.Upload w={14} /> {pushNow.isPending ? "Pushing…" : "Push now"}
          </Button>
          <Button variant="secondary" size="sm" disabled={!running} onClick={openForm}>Edit</Button>
          <Button variant="danger" size="sm" aria-label="Unlink remote" onClick={() => setUnlinkOpen(true)}>
            <Icons.Trash w={14} />
          </Button>
        </div>
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)",
      }}>
        <Switch
          on={r.enabled}
          aria-label="Auto-push"
          onClick={async () => {
            try {
              await save.mutateAsync({ url: r.url, branch: r.branch, enabled: !r.enabled });
              toast.success(r.enabled ? "Auto-push disabled" : "Auto-push enabled");
            } catch (err) {
              toast.error("Couldn't update auto-push", err instanceof ApiError ? err.message : undefined);
            }
          }}
        />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, color: "var(--ink-2)" }}>Auto-push after each task</div>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
            When on, every completed task's snapshot is pushed to the remote.
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={unlinkOpen}
        title="Unlink remote"
        body="Stops mirroring this workspace and deletes the stored credentials. The remote repository itself is not touched."
        confirmLabel="Unlink"
        destructive
        onConfirm={async () => {
          setUnlinkOpen(false);
          try { await unlink.mutateAsync(); }
          catch (err) { toast.error("Couldn't unlink", err instanceof ApiError ? err.message : undefined); }
        }}
        onCancel={() => setUnlinkOpen(false)}
      />
    </div>
  );
}

function SnapshotItem({
  cid, s, current, onRollback,
}: { cid: string; s: GitSnapshot; current: boolean; onRollback: (s: GitSnapshot) => void }) {
  const reinit = s.message === "repository reinitialized";
  return (
    <li className="tl-item">
      <span className={`tl-dot ${current ? "current" : ""} ${reinit ? "reset" : ""}`.replace(/\s+/g, " ").trim()} aria-hidden />
      <div className="tl-row">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: 13.5 }}>{s.message}</span>
            {current && <Pill tone="running">current</Pill>}
            {reinit && <span className="tag">history reset</span>}
          </div>
          <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", fontSize: 11.5, color: "var(--muted)" }}>
            <span className="tag">{shortSha(s.sha)}</span>
            <span title={absUnix(s.ts)}>{relUnix(s.ts)}</span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <Icons.File w={12} />
              <span className="num">{s.files_changed}</span> {s.files_changed === 1 ? "file" : "files"}
            </span>
            {s.task_id && (
              <Link
                to={`/containers/${cid}/tasks/${s.task_id}`}
                className="tag"
                style={{ display: "inline-flex", alignItems: "center", gap: 5, textDecoration: "none" }}
                title="View the task that created this snapshot"
              >
                <Icons.Tasks w={12} /> task
              </Link>
            )}
          </div>
        </div>
        {!current && (
          <Button size="sm" variant="secondary" onClick={() => onRollback(s)} style={{ flexShrink: 0 }}>Roll back</Button>
        )}
      </div>
    </li>
  );
}

export default function Snapshots() {
  const { cid = "" } = useParams<{ cid: string }>();
  const { data, isLoading } = useGitSnapshots(cid);
  const { data: container } = useContainer(cid);
  const rollback = useGitRollback(cid);
  const toast = useToast();
  const [target, setTarget] = useState<GitSnapshot | null>(null);

  const running = container?.status === "running";
  const snapshots = data?.snapshots ?? [];

  // Linked (pull) mode: git history is managed by the agent, so snapshots and
  // the backup remote are unavailable. Short-circuit before the normal render.
  if (container?.git_mode === "linked") {
    const linked = (data as { linked?: { url: string; branch: string } | null })?.linked ?? null;
    return (
      <div style={{ display: "grid", gap: 16 }}>
        <div className="card">
          <EmptyState
            icon="Code"
            title="Snapshots are off"
            description={
              <>
                This workspace is linked to{" "}
                <span className="mono">{linked?.url ?? "a git repository"}</span>
                {linked?.branch ? <> on branch <span className="mono">{linked.branch}</span></> : null}
                . Git history is managed by the agent, so restore points and the
                backup remote are unavailable here.
              </>
            }
            actions={<Link to={`/containers/${cid}/files`}>Manage the link in Files</Link>}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <RemoteCard cid={cid} running={running} />

      {/* Restore points */}
      <section>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em" }}>Restore points</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
              Every task auto-creates one. Rolling back is non-destructive: it adds a new snapshot you can undo.
            </div>
          </div>
          {!isLoading && snapshots.length > 0 && (
            <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted)" }}>
              {snapshots.length} snapshot{snapshots.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <div className="card" style={{ padding: "8px 16px" }}>
          {isLoading ? (
            <ol className="timeline" aria-busy="true" aria-label="Loading restore points">
              {[0, 1, 2].map((i) => (
                <li className="tl-item" key={i}>
                  <span className="tl-dot" aria-hidden />
                  <div className="tl-row">
                    <div style={{ display: "grid", gap: 6 }}>
                      <span className="skel" style={{ width: 220, height: 12 }} />
                      <span className="skel" style={{ width: 160, height: 10 }} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          ) : snapshots.length === 0 ? (
            <EmptyState
              size="sm"
              icon="Pin"
              title="No restore points yet"
              description="Run a task in this container and its workspace changes are captured here automatically."
            />
          ) : (
            <ol className="timeline">
              {snapshots.map((s, i) => (
                <SnapshotItem key={s.sha} cid={cid} s={s} current={i === 0} onRollback={setTarget} />
              ))}
            </ol>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={target !== null}
        title="Roll back workspace"
        body={`Restores the workspace to "${target?.message ?? ""}" (${target ? shortSha(target.sha) : ""}). This creates a new snapshot. Nothing is deleted, and you can roll back the rollback.`}
        confirmLabel="Roll back"
        onConfirm={async () => {
          const s = target!;
          setTarget(null);
          try { await rollback.mutateAsync(s.sha); toast.success("Workspace rolled back"); }
          catch (err) { toast.error("Rollback failed", err instanceof ApiError ? err.message : undefined); }
        }}
        onCancel={() => setTarget(null)}
      />
    </div>
  );
}
