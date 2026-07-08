import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  useSaveSkill, useRefreshSkill, fetchSkill, useSkillGitRefs, useSkillGitDiscover,
  useRecommendedSkills, useDeployKeys, useCreateDeployKey,
} from "../../api/queries";
import { useToast } from "../../components/Toast";
import { CopyButton } from "../../components/CopyButton";
import { ApiError } from "../../api/client";
import { Button, Field, Note } from "../../ui";
import { Input, Textarea, Switch } from "../../ui/inputs";
import { SegControl } from "../../ui/SegControl";
import { Dropdown } from "../../ui/Dropdown";
import { Icons } from "../../ui/Icon";
import { sourceUrlError, normalizeSourceUrl, repoLabel } from "../../lib/skillSource";
import { slugNameError } from "../../lib/validation";
import { formatOptionalBytes } from "../../lib/format";
import { groupByCategory, type RecommendedSkill, type RecommendedRepo } from "../../lib/recommendedSkills";
import type { Skill } from "../../api/types";
import type { DeployKey, DiscoveredSkill } from "../../api/queries";

// On create the user picks a source: a curated recommendation (installed via
// git), an inline-authored skill, or an arbitrary git repo. On edit the mode is
// fixed to the persisted source_type.
type Mode = "recommended" | "inline" | "git";

type Draft = {
  id?: string;
  source_type: "inline" | "git";
  name: string;
  description: string;
  body: string;
  enabled: boolean;
  source_url: string;
  source_subpath: string;
  source_ref: string;
  deploy_key_id: string;
};

// Sentinel option in the Ref dropdown that switches to free-text entry.
const CUSTOM_REF = "__custom_ref__";

const EMPTY: Draft = {
  source_type: "inline",
  name: "", description: "", body: "", enabled: true,
  source_url: "", source_subpath: "", source_ref: "", deploy_key_id: "",
};

export default function SkillEditor() {
  const { id } = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const save = useSaveSkill();
  const refresh = useRefreshSkill();
  const gitRefs = useSkillGitRefs();
  const deployKeysQuery = useDeployKeys();
  const createDeployKey = useCreateDeployKey();
  const deployKeys = deployKeysQuery.data ?? [];

  const initialSource = searchParams.get("source") === "git" ? "git" : "inline";
  const [draft, setDraft] = useState<Draft | null>(id ? null : { ...EMPTY, source_type: initialSource });
  const [loaded, setLoaded] = useState<Skill | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Create-screen source tab. Recommended is the default landing tab; ?source=
  // git|inline opens those directly (e.g. the list's "Install from git" link).
  const sourceParam = searchParams.get("source");
  const initialMode: Mode =
    sourceParam === "git" ? "git" : sourceParam === "inline" ? "inline" : "recommended";
  const [mode, setMode] = useState<Mode>(initialMode);
  // Recommended tab: multiple skills can be queued for install at once.
  const [selected, setSelected] = useState<RecommendedSkill[]>([]);
  const [installing, setInstalling] = useState(false);
  const toggleSkill = (s: RecommendedSkill) =>
    setSelected((prev) =>
      prev.some((x) => x.id === s.id) ? prev.filter((x) => x.id !== s.id) : [...prev, s],
    );

  // Branch picker for git skills: refs are loaded from the repo when the URL
  // field blurs. "idle"/"loading" disable the ref combobox; "ok" enables it with
  // the branch datalist; "error" leaves it enabled for manual ref entry.
  const [branches, setBranches] = useState<string[]>([]);
  const [refsState, setRefsState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [refsError, setRefsError] = useState<string | null>(null);
  // When branches are listed the Ref field is the console's styled Dropdown;
  // this flips it back to a free-text input for tags/commit SHAs.
  const [customRef, setCustomRef] = useState(false);
  const refsSeq = useRef(0);

  // Repo scan for the create form: every SKILL.md dir at the chosen ref.
  // Same stale-response guard as loadBranches (URL/ref/key can change mid-scan).
  const gitDiscover = useSkillGitDiscover();
  const [discovered, setDiscovered] = useState<DiscoveredSkill[] | null>(null);
  const [discoverState, setDiscoverState] =
    useState<"idle" | "loading" | "ok" | "error">("idle");
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discoverTruncated, setDiscoverTruncated] = useState(false);
  // Subpaths the user checked for install (auto-filled for single-skill repos).
  const [pickedSubpaths, setPickedSubpaths] = useState<string[]>([]);
  // Escape hatch: type the subpath by hand (scan failed, capped, odd repo).
  const [manualSubpath, setManualSubpath] = useState(false);
  const discoverSeq = useRef(0);

  const togglePicked = (subpath: string) =>
    setPickedSubpaths((prev) =>
      prev.includes(subpath) ? prev.filter((s) => s !== subpath) : [...prev, subpath],
    );

  // Re-scan whenever the inputs that define "which repo at which ref" change.
  // Guards use draft fields directly: isEdit/isGit are declared after the
  // component's early returns, and a hook must run unconditionally before
  // them. gitDiscover is intentionally not a dependency (mutation identity
  // churns); loadDiscovery is an `async function` declaration, so it hoists.
  // While the free-text ref editor is showing (customRef, or refs not listed
  // yet/failed) every keystroke updates source_ref and each scan is a
  // server-side clone — skip here and let the field's onBlur run the scan
  // once (same idiom as the URL field's onBlur -> loadBranches). Refs loading
  // ("ok") or switching back to the dropdown re-fires the scan.
  useEffect(() => {
    if (!draft || draft.id || draft.source_type !== "git" || manualSubpath) return;
    if (customRef || refsState !== "ok") return; // free-text ref editor active: scan on its blur
    void loadDiscovery();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.source_url, draft?.source_ref, draft?.deploy_key_id, draft?.source_type, manualSubpath, customRef, refsState]);

  // Repository access: the deploy-key picker only appears for private repos
  // (progressive disclosure — most installs are public).
  const [accessMode, setAccessMode] = useState<"public" | "private">("public");
  // Inline "Generate new deploy key" affordance under the deploy-key picker.
  const [showGenerateKey, setShowGenerateKey] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [justCreatedKey, setJustCreatedKey] = useState<DeployKey | null>(null);

  function switchAccessMode(v: "public" | "private") {
    // Auto-select the key when there's exactly one — the common case.
    const nextKey = v === "private" && deployKeys.length === 1 ? deployKeys[0].id : "";
    setAccessMode(v);
    setDraft((d) => (d ? { ...d, deploy_key_id: nextKey } : d));
    setRefsState("idle"); setBranches([]); setRefsError(null);
    setJustCreatedKey(null); setShowGenerateKey(false); setNewKeyName("");
    // The auth context changed, so re-list branches without waiting for
    // another URL blur (skip private-with-no-key: nothing to fetch with yet).
    if (v === "public" || nextKey) void loadBranches(nextKey);
  }

  // Edit: fetch the full skill (incl. body) once.
  useEffect(() => {
    if (!id || draft) return;
    let alive = true;
    fetchSkill(id)
      .then((full) => {
        if (!alive) return;
        setLoaded(full);
        setDraft({
          id: full.id, source_type: full.source_type,
          name: full.name, description: full.description, body: full.body ?? "",
          enabled: full.enabled,
          source_url: full.source_url ?? "", source_subpath: full.source_subpath ?? "",
          source_ref: full.source_ref ?? "", deploy_key_id: full.deploy_key_id ?? "",
        });
      })
      .catch(() => { if (alive) setLoadError(true); });
    return () => { alive = false; };
  }, [id, draft]);

  function back() { navigate("/settings/skills"); }

  if (id && loadError) {
    return (
      <div className="page" style={{ maxWidth: 720 }}>
        <Note tone="amber">
          Couldn't load this skill. It may have been deleted.{" "}
          <button className="btn btn-ghost btn-sm" onClick={back}>Back to skills</button>
        </Note>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="page" style={{ maxWidth: 720 }}>
        <div className="skel" style={{ width: 180, height: 16, marginBottom: 12 }} />
        <div className="card" style={{ display: "grid", gap: 12 }}>
          <div className="skel" style={{ width: "60%", height: 12 }} />
          <div className="skel" style={{ width: "90%", height: 12 }} />
          <div className="skel" style={{ width: "40%", height: 12 }} />
        </div>
      </div>
    );
  }

  const isEdit = !!draft.id;
  const effMode: Mode = isEdit ? draft.source_type : mode;
  const isRecommended = effMode === "recommended";
  const isGit = effMode === "git";
  const invalidName = isGit || isRecommended ? null : slugNameError(draft.name, "git-release");
  // Users paste whichever URL form they copied; we convert to the scheme the
  // backend requires (ssh with a key, https without) instead of erroring.
  const effectiveUrl = isGit ? normalizeSourceUrl(draft.source_url, !!draft.deploy_key_id) : "";
  const invalidUrl = isGit ? sourceUrlError(effectiveUrl, !!draft.deploy_key_id) : null;
  const urlConverted = isGit && !!effectiveUrl && effectiveUrl !== draft.source_url.trim();
  const busy = save.isPending || installing;
  const selectedKey = deployKeys.find((k) => k.id === draft.deploy_key_id) ?? null;
  const refsAuthFailed = refsState === "error" && !!refsError?.startsWith("auth_failed");
  const canSave = isRecommended
    ? selected.length > 0
    : isGit
      ? !!draft.source_url && !invalidUrl && !!draft.source_ref
        && (isEdit || accessMode === "public" || !!draft.deploy_key_id)
        && (isEdit || manualSubpath || pickedSubpaths.length > 0)
      : !!draft.name && !!draft.description && !invalidName;

  // Load the repo's branches when the URL field blurs (after normalizing the
  // pasted URL to the scheme the backend expects for the chosen access).
  // keyIdOverride lets callers that just changed the key (dropdown, access
  // switch, generate) fetch with the NEW key before React re-renders the
  // closure. A sequence counter drops stale responses from superseded calls.
  async function loadBranches(keyIdOverride?: string) {
    if (!draft) return;
    const keyId = keyIdOverride !== undefined ? keyIdOverride : draft.deploy_key_id;
    const url = normalizeSourceUrl(draft.source_url, !!keyId);
    if (!url || sourceUrlError(url, !!keyId)) { setRefsState("idle"); setBranches([]); return; }
    const seq = ++refsSeq.current;
    setRefsState("loading");
    setRefsError(null);
    setCustomRef(false);
    try {
      const res = await gitRefs.mutateAsync({ source_url: url, deploy_key_id: keyId || undefined });
      if (seq !== refsSeq.current) return;
      setBranches(res.branches);
      setRefsState("ok");
      const def = res.default_branch;
      if (def) {
        setDraft((d) => (d && (d.source_ref === "" || d.source_ref === "main")
          ? { ...d, source_ref: def } : d));
      }
    } catch (err) {
      if (seq !== refsSeq.current) return;
      setRefsState("error");
      setBranches([]);
      setRefsError(err instanceof ApiError ? err.message : "Couldn't list branches");
    }
  }

  // Scan the repo (at the current URL/ref/key) for every SKILL.md dir. Same
  // stale-response guard as loadBranches: a sequence counter drops responses
  // superseded by a newer scan triggered while this one was in flight.
  async function loadDiscovery() {
    if (!draft || draft.id) return;
    const url = normalizeSourceUrl(draft.source_url, !!draft.deploy_key_id);
    if (!url || sourceUrlError(url, !!draft.deploy_key_id) || !draft.source_ref) {
      setDiscoverState("idle"); setDiscovered(null); setPickedSubpaths([]);
      return;
    }
    const seq = ++discoverSeq.current;
    setDiscoverState("loading");
    setDiscoverError(null);
    try {
      const res = await gitDiscover.mutateAsync({
        source_url: url, source_ref: draft.source_ref,
        deploy_key_id: draft.deploy_key_id || undefined,
      });
      if (seq !== discoverSeq.current) return;
      setDiscovered(res.skills);
      setDiscoverTruncated(res.truncated);
      setDiscoverState("ok");
      const usable = res.skills.filter((s) => s.valid && !s.installed);
      // Single-skill repo: pick it automatically — Save behaves as before.
      setPickedSubpaths(
        res.skills.length === 1 && usable.length === 1 ? [usable[0].subpath] : [],
      );
    } catch (err) {
      if (seq !== discoverSeq.current) return;
      setDiscoverState("error");
      setDiscovered(null);
      setPickedSubpaths([]);
      setDiscoverError(err instanceof ApiError ? err.message : "Couldn't scan the repository");
    }
  }

  // Prefill for the generate-key form, derived from the pasted repo (org-repo).
  function suggestedKeyName(): string {
    if (!draft) return "";
    const https = normalizeSourceUrl(draft.source_url, false);
    const m = /^https:\/\/[^/]+\/(\S+?)(?:\.git)?\/?$/.exec(https);
    if (!m) return "";
    return m[1].toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
  }

  async function onGenerateKey() {
    if (!newKeyName.trim()) return;
    try {
      const key = await createDeployKey.mutateAsync(newKeyName.trim());
      setDraft((d) => (d ? { ...d, deploy_key_id: key.id } : d));
      setJustCreatedKey(key);
      setShowGenerateKey(false);
      setNewKeyName("");
      setRefsState("idle");
      setBranches([]);
      setRefsError(null);
      // Probe right away: until the public key is installed on the repo this
      // surfaces the "not installed yet" hint with the key and a Retry.
      void loadBranches(key.id);
    } catch (err) {
      toast.error("Couldn't generate deploy key", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onSave() {
    if (!draft || !canSave) return;
    try {
      if (isRecommended) {
        if (selected.length === 0) return;
        // Each pick carries its own branch + subpath, so install straight through
        // the git path. Install sequentially and report any partial failures
        // (e.g. a name clash) rather than aborting the whole batch.
        setInstalling(true);
        const failed: { id: string; label: string; msg: string }[] = [];
        let ok = 0;
        for (const s of selected) {
          try {
            await save.mutateAsync({
              source_type: "git", source_url: s.url,
              source_subpath: s.subpath, source_ref: s.branch,
              enabled: draft.enabled,
            });
            ok++;
          } catch (err) {
            failed.push({
              id: s.id, label: `${s.repoName}/${s.label}`,
              msg: err instanceof ApiError ? err.message : "install failed",
            });
          }
        }
        setInstalling(false);
        if (ok > 0) toast.success(`${ok} skill${ok === 1 ? "" : "s"} installed`);
        if (failed.length) {
          toast.error(
            `${failed.length} skill${failed.length === 1 ? "" : "s"} couldn't be installed`,
            failed.map((f) => `${f.label}: ${f.msg}`).join("\n"),
          );
          // Keep only the failures selected so the user can adjust or retry.
          setSelected((prev) => prev.filter((s) => failed.some((f) => f.id === s.id)));
          return;
        }
        navigate("/settings/skills");
        return;
      } else if (isGit && !draft.id && !manualSubpath) {
        const picks = (discovered ?? []).filter((s) => pickedSubpaths.includes(s.subpath));
        if (picks.length === 0) return;
        // Same sequential batch as the recommended flow: report partial
        // failures (e.g. a name clash) rather than aborting the whole batch.
        setInstalling(true);
        const failed: { subpath: string; label: string; msg: string }[] = [];
        let ok = 0;
        for (const s of picks) {
          try {
            await save.mutateAsync({
              source_type: "git",
              source_url: normalizeSourceUrl(draft.source_url, !!draft.deploy_key_id),
              source_subpath: s.subpath, source_ref: draft.source_ref,
              enabled: draft.enabled, deploy_key_id: draft.deploy_key_id || null,
            });
            ok++;
          } catch (err) {
            failed.push({
              subpath: s.subpath, label: s.name || s.subpath,
              msg: err instanceof ApiError ? err.message : "install failed",
            });
          }
        }
        setInstalling(false);
        if (ok > 0) toast.success(`${ok} skill${ok === 1 ? "" : "s"} installed`);
        if (failed.length) {
          toast.error(
            `${failed.length} skill${failed.length === 1 ? "" : "s"} couldn't be installed`,
            failed.map((f) => `${f.label}: ${f.msg}`).join("\n"),
          );
          // Keep only the failures picked so the user can adjust or retry.
          setPickedSubpaths(failed.map((f) => f.subpath));
          return;
        }
        navigate("/settings/skills");
        return;
      } else if (isGit) {
        await save.mutateAsync({
          id: draft.id, source_type: "git",
          source_url: normalizeSourceUrl(draft.source_url, !!draft.deploy_key_id),
          source_subpath: draft.source_subpath,
          source_ref: draft.source_ref, enabled: draft.enabled,
          deploy_key_id: draft.deploy_key_id || null,
        });
        toast.success(draft.id ? "Skill updated" : "Skill installed");
      } else {
        await save.mutateAsync({
          id: draft.id, source_type: "inline",
          name: draft.name, description: draft.description,
          body: draft.body, enabled: draft.enabled,
        });
        toast.success(draft.id ? "Skill updated" : "Skill created");
      }
      navigate("/settings/skills");
    } catch (err) {
      toast.error("Couldn't save skill", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onRefresh() {
    if (!draft?.id) return;
    try {
      await refresh.mutateAsync(draft.id);
      const full = await fetchSkill(draft.id);
      setLoaded(full);
      setDraft((d) => (d ? { ...d, name: full.name, description: full.description, body: full.body ?? "" } : d));
      toast.success("Skill re-pinned");
    } catch (err) {
      toast.error("Couldn't refresh skill", err instanceof ApiError ? err.message : undefined);
    }
  }

  const previewMd =
    `---\nname: ${draft.name || "skill-name"}\ndescription: ${JSON.stringify(draft.description || "")}\n---\n\n` +
    (draft.body || "");

  const installs = isRecommended || (isGit && !draft.id);
  const gitPickCount = isGit && !draft.id && !manualSubpath ? pickedSubpaths.length : 0;
  const saveLabel = busy
    ? (installs ? "Installing…" : "Saving…")
    : isRecommended
      ? (selected.length > 1 ? `Install ${selected.length} skills` : "Install skill")
      : gitPickCount > 1
        ? `Install ${gitPickCount} skills`
        : (installs ? "Install skill" : "Save skill");
  const bundleSize = formatOptionalBytes(loaded?.bundle_size);

  return (
    <div
      className="responsive-editor responsive-split"
      style={{
        display: "grid", gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 1fr)",
        height: "100%", overflow: "hidden", background: "var(--surface)",
      }}
    >
      {/* LEFT — form */}
      <div
        className="responsive-editor-pane"
        style={{
          overflow: "auto", padding: "22px 24px 28px", display: "flex",
          flexDirection: "column", gap: 18, borderRight: "1px solid var(--border)",
        }}
      >
        <div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={back}
            style={{ gap: 6, padding: "4px 8px 4px 4px", marginBottom: 8, marginLeft: -4 }}
          >
            <Icons.ArrowLeft w={15} /> Skills
          </button>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {draft.id ? "Edit skill" : "New skill"}
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            {isRecommended
              ? "Pick one or more community-recommended skills and install them from their repositories."
              : isGit
                ? "Install a published skill from a git repository, pinned to a commit."
                : "Author the instructions the opencode and codex drivers load on demand."}
          </div>
        </div>

        {/* Source toggle — create only. Wrapped so the inline-flex control sizes
            to its content instead of stretching to fill the column flex parent. */}
        {!draft.id && (
          <div>
            <SegControl<Mode>
              value={mode}
              onChange={(v) => { setMode(v); if (v !== "recommended") setDraft({ ...draft, source_type: v }); }}
              options={[
                { value: "recommended", label: "Recommended" },
                { value: "inline", label: "Inline" },
                { value: "git", label: "From git" },
              ]}
            />
          </div>
        )}

        {isRecommended ? (
          <RecommendedCatalog selected={selected} onToggle={toggleSkill} />
        ) : isGit ? (
          draft.id ? (
            <Field label="Source">
              <div
                style={{
                  display: "grid", gap: 8, padding: "12px 14px", background: "var(--surface-2)",
                  border: "1px solid var(--border)", borderRadius: "var(--r-3)", fontSize: 13,
                }}
              >
                <SummaryRow label="Repository" value={<span className="mono">{repoLabel(draft.source_url)}</span>} />
                {draft.deploy_key_id && (
                  <SummaryRow
                    label="Access"
                    value={
                      <span className="chip" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, padding: "3px 8px" }}>
                        <Icons.Key w={12} /> {selectedKey?.name ?? "deploy key"}
                      </span>
                    }
                  />
                )}
                {draft.source_subpath && <SummaryRow label="Subpath" value={<span className="mono">{draft.source_subpath}</span>} />}
                <SummaryRow label="Ref" value={<span className="mono">{draft.source_ref}</span>} />
                {loaded?.pinned_sha && <SummaryRow label="Pinned" value={<span className="tag">{loaded.pinned_sha.slice(0, 12)}</span>} />}
                {bundleSize && <SummaryRow label="Bundle" value={bundleSize} />}
                <div style={{ marginTop: 2 }}>
                  <Button variant="secondary" size="sm" onClick={onRefresh} disabled={refresh.isPending} style={{ gap: 6 }}>
                    <Icons.Refresh w={14} /> {refresh.isPending ? "Re-pinning…" : "Update / re-pin"}
                  </Button>
                </div>
              </div>
            </Field>
          ) : (
            <>
              <Field label="Repository URL" htmlFor="git-url" hint="Paste the repository URL — https or ssh both work.">
                <Input id="git-url" className="fluid-w" aria-label="Repository URL" value={draft.source_url}
                  aria-invalid={!!invalidUrl}
                  onChange={(e) => { setDraft({ ...draft, source_url: e.target.value }); setRefsState("idle"); setBranches([]); }}
                  onBlur={() => loadBranches()}
                  placeholder="https://github.com/org/repo" />
                {invalidUrl && <span className="hint" role="alert" style={{ color: "var(--err-700)" }}>{invalidUrl}</span>}
                {!invalidUrl && refsState === "loading" && (
                  <span className="hint">Checking repository…</span>
                )}
                {!invalidUrl && refsState !== "loading" && urlConverted && (
                  <span className="hint">
                    Connects as <span className="mono">{effectiveUrl}</span>
                  </span>
                )}
                {refsAuthFailed && !draft.deploy_key_id && (
                  <div style={{ marginTop: 8 }}>
                    <Note tone="amber" role="alert" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span>This repository looks private.</span>
                      <Button variant="secondary" size="sm" onClick={() => switchAccessMode("private")}>
                        Use a deploy key
                      </Button>
                    </Note>
                  </div>
                )}
                {refsAuthFailed && !!draft.deploy_key_id && (
                  <div style={{ marginTop: 8 }}>
                    <Note tone="amber" role="alert">
                      The key isn&apos;t installed on this repo yet — add the public key below as a read-only
                      deploy key, then retry.
                    </Note>
                    {selectedKey && (
                      <div style={{ marginTop: 8 }}>
                        <DeployKeyInstallHint publicKey={selectedKey.ssh_public_key} />
                      </div>
                    )}
                    <div style={{ marginTop: 8 }}>
                      <Button variant="secondary" size="sm" onClick={() => loadBranches()} style={{ gap: 6 }}>
                        <Icons.Refresh w={13} /> Retry
                      </Button>
                    </div>
                  </div>
                )}
              </Field>
              <Field label="Repository access">
                <div>
                  <SegControl<"public" | "private">
                    value={accessMode}
                    onChange={switchAccessMode}
                    options={[
                      { value: "public", label: "Public" },
                      { value: "private", label: "Private" },
                    ]}
                  />
                </div>
                {accessMode === "private" && (
                  <div
                    style={{
                      marginTop: 8, display: "grid", gap: 10, padding: "12px 14px",
                      background: "var(--surface-2)", border: "1px solid var(--border)",
                      borderRadius: "var(--r-3)",
                    }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Dropdown
                          id="deploy-key-sel"
                          aria-label="Deploy key"
                          value={draft.deploy_key_id}
                          onChange={(v) => {
                            setDraft({ ...draft, deploy_key_id: v });
                            setRefsState("idle"); setBranches([]); setRefsError(null); setJustCreatedKey(null);
                            if (v) void loadBranches(v);
                          }}
                          options={[
                            { value: "", label: "Select a deploy key…" },
                            ...deployKeys.map((k) => ({ value: k.id, label: k.name })),
                          ]}
                        />
                      </div>
                      {!showGenerateKey && (
                        <Button
                          variant="secondary"
                          style={{ gap: 6, flexShrink: 0, whiteSpace: "nowrap", fontSize: 12.5, padding: "0 14px" }}
                          onClick={() => { setNewKeyName(suggestedKeyName()); setShowGenerateKey(true); }}
                        >
                          <Icons.Plus w={13} /> Generate new deploy key…
                        </Button>
                      )}
                    </div>
                    {showGenerateKey && (
                      <div style={{ display: "grid", gap: 6 }}>
                        <label htmlFor="new-key-name" style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)" }}>
                          Key name
                        </label>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <Input
                            id="new-key-name"
                            aria-label="New deploy key name"
                            value={newKeyName}
                            onChange={(e) => setNewKeyName(e.target.value)}
                            placeholder="org-repo"
                            style={{ maxWidth: 220 }}
                          />
                          <Button variant="primary" size="sm" disabled={!newKeyName.trim() || createDeployKey.isPending} onClick={onGenerateKey}>
                            {createDeployKey.isPending ? "Generating…" : "Generate"}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => { setShowGenerateKey(false); setNewKeyName(""); }}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}
                    {justCreatedKey && (
                      <div style={{ display: "grid", gap: 8, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600 }}>
                          <Icons.Check w={14} /> Key &quot;{justCreatedKey.name}&quot; created — add it to GitHub
                        </div>
                        <DeployKeyInstallHint publicKey={justCreatedKey.ssh_public_key} />
                      </div>
                    )}
                  </div>
                )}
              </Field>
              {manualSubpath ? (
                <Field label="Subpath" hint="Directory containing SKILL.md. Leave blank for the repo root." htmlFor="git-subpath">
                  <Input id="git-subpath" className="fluid-w" aria-label="Subpath" value={draft.source_subpath}
                    onChange={(e) => setDraft({ ...draft, source_subpath: e.target.value })}
                    placeholder="skills/pdf" />
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ gap: 6, padding: "4px 6px", marginTop: 6, alignSelf: "start" }}
                    onClick={() => setManualSubpath(false)}
                  >
                    Discover skills automatically instead
                  </button>
                </Field>
              ) : (
                <Field label="Skills in this repository">
                  {discoverState === "idle" && (
                    <span className="hint">Enter the repository URL and pick a ref to list its skills.</span>
                  )}
                  {discoverState === "loading" && (
                    <div style={{ display: "grid", gap: 8 }}>
                      <div className="skel" style={{ width: "70%", height: 12 }} />
                      <div className="skel" style={{ width: "50%", height: 12 }} />
                    </div>
                  )}
                  {discoverState === "error" && (
                    <Note tone="amber" role="alert" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span>Couldn't scan the repository{discoverError ? ` (${discoverError})` : ""}.</span>
                      <Button variant="secondary" size="sm" onClick={() => void loadDiscovery()} style={{ gap: 6 }}>
                        <Icons.Refresh w={13} /> Retry
                      </Button>
                    </Note>
                  )}
                  {discoverState === "ok" && discovered && discovered.length === 0 && (
                    <Note tone="amber">No skills found at this ref — the repository has no SKILL.md.</Note>
                  )}
                  {discoverState === "ok" && discovered && discovered.length > 0 && (
                    <div
                      style={{
                        display: "grid", gap: 2, padding: "6px 8px",
                        background: "var(--surface-2)", border: "1px solid var(--border)",
                        borderRadius: "var(--r-3)",
                      }}
                    >
                      {discovered.map((s) => {
                        const disabled = !s.valid || s.installed;
                        return (
                          <label
                            key={s.subpath || "(root)"}
                            style={{
                              display: "flex", gap: 10, alignItems: "flex-start",
                              padding: "8px 6px", borderRadius: "var(--r-2)",
                              cursor: disabled ? "default" : "pointer",
                              opacity: disabled ? 0.55 : 1,
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={pickedSubpaths.includes(s.subpath)}
                              disabled={disabled}
                              onChange={() => togglePicked(s.subpath)}
                              style={{ marginTop: 3 }}
                            />
                            <span style={{ display: "grid", gap: 2, minWidth: 0 }}>
                              <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                                <span style={{ fontSize: 13, fontWeight: 600 }}>
                                  {s.name || <span className="mono">{s.subpath || "(repo root)"}</span>}
                                </span>
                                {s.installed && <span className="tag">installed</span>}
                                {!s.valid && <span className="tag" style={{ color: "var(--err-700)" }}>invalid</span>}
                              </span>
                              <span className="hint" style={{ margin: 0 }}>
                                {s.valid ? s.description : s.error}
                              </span>
                              {s.subpath && <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{s.subpath}</span>}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                  {discoverState === "ok" && discoverTruncated && (
                    <span className="hint" style={{ color: "var(--warn-700)" }}>
                      Listing capped at 50 skills — use the manual subpath for anything beyond.
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ gap: 6, padding: "4px 6px", marginTop: 6, alignSelf: "start" }}
                    onClick={() => setManualSubpath(true)}
                  >
                    Enter a subpath manually instead
                  </button>
                </Field>
              )}
              <Field label="Ref" hint="Branch, tag, or commit SHA. Resolved and pinned at install." htmlFor="git-ref">
                {refsState === "ok" && !customRef ? (
                  <>
                    <Dropdown
                      id="git-ref"
                      aria-label="Ref"
                      value={draft.source_ref}
                      onChange={(v) => {
                        if (v === CUSTOM_REF) { setCustomRef(true); return; }
                        setDraft({ ...draft, source_ref: v });
                      }}
                      options={[
                        ...branches.map((b) => ({ value: b, label: b })),
                        { value: CUSTOM_REF, label: "Enter a tag or commit SHA…" },
                      ]}
                    />
                  </>
                ) : (
                  <>
                    <Input id="git-ref" className="fluid-w" aria-label="Ref" value={draft.source_ref}
                      onChange={(e) => setDraft({ ...draft, source_ref: e.target.value })}
                      onBlur={() => { if (!manualSubpath) void loadDiscovery(); }}
                      placeholder={refsState === "loading" ? "Loading branches…" : "main"} />
                    {refsState === "ok" && customRef && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{ gap: 6, padding: "4px 6px", marginTop: 6, alignSelf: "start" }}
                        onClick={() => setCustomRef(false)}
                      >
                        Choose from branches instead
                      </button>
                    )}
                  </>
                )}
                {refsState === "error" && !refsAuthFailed && (
                  <span className="hint" style={{ color: "var(--warn-700)" }}>
                    Couldn't list branches{refsError ? ` (${refsError})` : ""}. Enter a ref manually.
                  </span>
                )}
              </Field>
            </>
          )
        ) : (
          <>
            <Field label="Name" hint="Used as the skill's folder name." htmlFor="skill-name">
              <Input id="skill-name" className="fluid-w" aria-label="Name" value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="git-release" disabled={!!draft.id} aria-invalid={!!invalidName} />
              {invalidName && <span className="hint" style={{ color: "var(--err-700)" }}>{invalidName}</span>}
            </Field>
            <Field label="Description" hint="What the model reads to decide when to load this skill." htmlFor="skill-desc">
              <Input id="skill-desc" className="fluid-w" aria-label="Description" value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                placeholder="Cut a release and publish the changelog" />
            </Field>
            <Field label="Instructions" hint="The markdown the model loads when it uses this skill." htmlFor="skill-body">
              <Textarea id="skill-body" aria-label="Instructions" value={draft.body}
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                placeholder={"# Steps\n1. …"}
                style={{ minHeight: 220, fontFamily: "var(--font-mono)", fontSize: 12.5 }} />
            </Field>
          </>
        )}

        {/* Enabled */}
        <Field label="Availability">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
              Enabled. Disabled skills stay in the library but aren't loaded by agents.
            </span>
            <Switch on={draft.enabled} aria-label="Enabled" onClick={() => setDraft({ ...draft, enabled: !draft.enabled })} />
          </div>
        </Field>
      </div>

      {/* RIGHT — preview + actions */}
      <div className="responsive-editor-pane" style={{ display: "flex", flexDirection: "column", minHeight: 0, background: "var(--surface-2)" }}>
        <div style={{ flex: 1, overflow: "auto", padding: "22px 20px" }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)", marginBottom: 10 }}>
            {isRecommended || (isGit && !draft.id) ? "What happens" : "SKILL.md preview"}
          </div>

          {isRecommended ? (
            selected.length ? (
              <>
                <Note>
                  Installs {selected.length} skill{selected.length === 1 ? "" : "s"}. Each is fetched from its
                  repository at the listed branch, pinned to an immutable commit, validated, and cached; the
                  name and description come from each <span className="mono">SKILL.md</span>.
                </Note>
                <div style={{ marginTop: 14, display: "grid", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)" }}>
                      Selected · {selected.length}
                    </span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSelected([])}>Clear</button>
                  </div>
                  {selected.map((s) => (
                    <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 6px 6px 10px", border: "1px solid var(--border)", borderRadius: "var(--r-2)", background: "var(--surface)" }}>
                      <span style={{ minWidth: 0, flex: 1, fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{s.label}</span>
                        <span style={{ color: "var(--muted)", marginLeft: 6, fontSize: 11 }}>{s.repoName}</span>
                      </span>
                      <button
                        aria-label={`Remove ${s.label}`}
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSelected((prev) => prev.filter((x) => x.id !== s.id))}
                        style={{ padding: "2px 8px", lineHeight: 1 }}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <Note tone="amber">Select one or more skills from the list to install.</Note>
            )
          ) : isGit && !draft.id ? (
            <Note>
              On install, the control plane fetches the repository at <b>{draft.source_ref || "the ref"}</b>,
              pins it to an immutable commit, validates its <span className="mono">SKILL.md</span>, and caches the
              bundle. The skill's name and description are read from its frontmatter.
            </Note>
          ) : (
            <div className="card" style={{ padding: 14 }}>
              <pre style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.6, whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--ink-2)" }}>
                {previewMd}
              </pre>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "12px 20px", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>
          <Button variant="secondary" size="md" onClick={back}>Cancel</Button>
          <Button variant="primary" size="md" onClick={onSave} disabled={!canSave || busy}>{saveLabel}</Button>
        </div>
      </div>
    </div>
  );
}

/** Public half of a deploy key + copy button + the GitHub install instruction.
    Shown right after generating a key, and again if a git-refs fetch reports
    auth_failed (the key exists but isn't installed on this particular repo). */
function DeployKeyInstallHint({ publicKey }: { publicKey: string }) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div
        className="mono"
        style={{
          background: "var(--surface-3)", border: "1px solid var(--border)",
          borderRadius: 8, padding: "10px 12px",
          fontSize: 12, overflowWrap: "anywhere",
        }}
      >
        {publicKey}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <CopyButton text={publicKey} label="Copy public key" />
        <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
          Add as a deploy key on GitHub (Settings &rarr; Deploy keys &rarr; Add deploy key). Leave
          &lsquo;Allow write access&rsquo; unchecked.
        </span>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 10 }}>
      <span style={{ color: "var(--muted)", width: 86, flex: "0 0 86px" }}>{label}</span>
      <span style={{ minWidth: 0, wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}

/** Searchable, category-grouped picker for the curated recommendation catalog.
    Rows are repositories; multi-skill repos expand to a capped, filterable list
    of their individual skills. Only mounted on the Recommended tab, so its fetch
    is deferred until opened. */
function RecommendedCatalog({
  selected, onToggle,
}: {
  selected: RecommendedSkill[];
  onToggle: (s: RecommendedSkill) => void;
}) {
  const { data, isLoading, isError, error, refetch } = useRecommendedSkills();
  const [q, setQ] = useState("");
  const [openRepo, setOpenRepo] = useState<string | null>(null);
  const [skillFilter, setSkillFilter] = useState("");

  const selectedIds = useMemo(() => new Set(selected.map((s) => s.id)), [selected]);
  const repoSelCount = (url: string) => selected.reduce((n, s) => (s.url === url ? n + 1 : n), 0);

  const groups = useMemo(() => {
    const all = data ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? all.filter(
          (r) =>
            r.repoName.toLowerCase().includes(needle) ||
            r.description.toLowerCase().includes(needle) ||
            r.category.toLowerCase().includes(needle),
        )
      : all;
    return groupByCategory(filtered);
  }, [data, q]);

  if (isLoading) return <CatalogSkeleton />;
  if (isError) {
    return (
      <Note tone="amber">
        Couldn't load recommended skills{error instanceof Error ? ` (${error.message})` : ""}.{" "}
        <button className="btn btn-ghost btn-sm" onClick={() => refetch()}>Retry</button>
      </Note>
    );
  }

  const total = data?.length ?? 0;
  const shown = groups.reduce((n, g) => n + g.items.length, 0);

  function clickRepo(r: RecommendedRepo) {
    if (r.skills.length === 1) {
      onToggle(r.skills[0]);
      setOpenRepo(r.id);
      return;
    }
    setSkillFilter("");
    setOpenRepo((prev) => (prev === r.id ? null : r.id));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="search-pill fluid-w">
        <Icons.Search />
        <input
          aria-label="Search recommended skills"
          placeholder="Search repositories…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
        {q.trim() ? `${shown} of ${total} repositories` : `${total} repositories`}
      </div>

      {groups.length === 0 ? (
        <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>
          No repositories match your search.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {groups.map((g) => (
            <div key={g.category}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)", marginBottom: 7 }}>
                {g.category}
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                {g.items.map((r) => {
                  const multi = r.skills.length > 1;
                  const selCount = repoSelCount(r.url);
                  const repoActive = selCount > 0;
                  const singleSelected = !multi && selectedIds.has(r.skills[0].id);
                  const open = openRepo === r.id || (repoActive && multi);
                  return (
                    <div key={r.id}>
                      <button
                        type="button"
                        onClick={() => clickRepo(r)}
                        aria-expanded={multi ? open : undefined}
                        aria-pressed={!multi ? singleSelected : undefined}
                        style={{
                          textAlign: "left", display: "flex", gap: 10, alignItems: "flex-start",
                          width: "100%", padding: "10px 12px", borderRadius: "var(--r-2)", cursor: "pointer",
                          border: `1px solid ${repoActive ? "var(--ink)" : "var(--border)"}`,
                          background: repoActive ? "var(--p-50)" : "var(--surface)",
                          transition: "border-color .12s ease, background .12s ease",
                        }}
                      >
                        <span aria-hidden style={{ marginTop: 1, width: 16, flex: "0 0 16px", textAlign: "center", color: repoActive ? "var(--ink)" : "var(--muted-2)", fontWeight: 700 }}>
                          {!multi ? (singleSelected ? "✓" : <Icons.Code w={15} />) : open ? "▾" : "▸"}
                        </span>
                        <span style={{ minWidth: 0, flex: 1 }}>
                          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontWeight: 600, fontSize: 13, fontFamily: "var(--font-mono)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.repoName}</span>
                            <span style={{ flex: "0 0 auto", fontSize: 10.5, color: "var(--muted)", border: "1px solid var(--border)", borderRadius: 999, padding: "1px 7px" }}>
                              {r.skills.length} {r.skills.length === 1 ? "skill" : "skills"}
                            </span>
                            {multi && selCount > 0 && (
                              <span style={{ flex: "0 0 auto", fontSize: 10.5, fontWeight: 700, color: "var(--ink)", background: "var(--p-300)", borderRadius: 999, padding: "1px 7px" }}>
                                {selCount} selected
                              </span>
                            )}
                          </span>
                          {r.description && (
                            <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 2, lineHeight: 1.45 }}>{r.description}</span>
                          )}
                        </span>
                      </button>
                      {multi && open && (
                        <SkillSublist repo={r} selectedIds={selectedIds} onToggle={onToggle} filter={skillFilter} setFilter={setSkillFilter} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const SKILL_CAP = 40;

function SkillSublist({
  repo, selectedIds, onToggle, filter, setFilter,
}: {
  repo: RecommendedRepo;
  selectedIds: Set<string>;
  onToggle: (s: RecommendedSkill) => void;
  filter: string;
  setFilter: (v: string) => void;
}) {
  const needle = filter.trim().toLowerCase();
  const matches = needle
    ? repo.skills.filter((s) => s.label.toLowerCase().includes(needle) || s.subpath.toLowerCase().includes(needle))
    : repo.skills;
  const shown = matches.slice(0, SKILL_CAP);

  return (
    <div style={{ marginTop: 6, marginLeft: 26, paddingLeft: 10, borderLeft: "1px solid var(--border)", display: "grid", gap: 6 }}>
      {repo.skills.length > 12 && (
        <input
          aria-label={`Filter ${repo.repoName} skills`}
          placeholder="Filter skills…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            width: "100%", padding: "6px 10px", fontSize: 12.5,
            border: "1px solid var(--border)", borderRadius: "var(--r-2)",
            background: "var(--surface)", color: "var(--ink)",
          }}
        />
      )}
      {shown.map((s) => {
        const active = selectedIds.has(s.id);
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onToggle(s)}
            aria-pressed={active}
            style={{
              textAlign: "left", display: "flex", gap: 8, alignItems: "center", width: "100%",
              padding: "7px 10px", borderRadius: "var(--r-2)", cursor: "pointer",
              border: `1px solid ${active ? "var(--ink)" : "var(--border)"}`,
              background: active ? "var(--p-50)" : "var(--surface)",
            }}
          >
            <span aria-hidden style={{ width: 12, flex: "0 0 12px", textAlign: "center", color: active ? "var(--ink)" : "var(--muted-2)", fontWeight: 700 }}>
              {active ? "✓" : "·"}
            </span>
            <span style={{ fontSize: 12.5, fontFamily: "var(--font-mono)" }}>{s.label}</span>
            <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s.subpath || "repo root"}
            </span>
          </button>
        );
      })}
      {matches.length > SKILL_CAP && (
        <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
          Showing {SKILL_CAP} of {matches.length}. Refine the filter to narrow down.
        </div>
      )}
      {matches.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--muted)" }}>No skills match that filter.</div>
      )}
    </div>
  );
}

function CatalogSkeleton() {
  return (
    <div style={{ display: "grid", gap: 8 }} aria-busy="true" aria-label="Loading recommended skills">
      <div className="skel" style={{ width: "100%", height: 36, borderRadius: 999 }} />
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="skel" style={{ width: "100%", height: 52, borderRadius: 8 }} />
      ))}
    </div>
  );
}
