import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useSkills, useDeleteSkill, useRefreshSkill } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { SegControl } from "../../ui/SegControl";
import { Icons } from "../../ui/Icon";
import { repoLabel } from "../../lib/skillSource";
import type { Skill } from "../../api/types";

type Filter = "all" | "inline" | "git";

/** Type glyph tile — Puzzle for inline skills, Code for git-sourced. */
function SkillGlyph({ git }: { git: boolean }) {
  return (
    <div
      aria-hidden
      style={{
        width: 34, height: 34, borderRadius: 9, flex: "0 0 34px",
        display: "grid", placeItems: "center", color: "var(--ink)",
        background: git ? "var(--surface-3)" : "var(--p-300)",
      }}
    >
      {git ? <Icons.Code w={17} /> : <Icons.Puzzle w={17} />}
    </div>
  );
}

export default function Skills() {
  const { data, isLoading } = useSkills();
  const del = useDeleteSkill();
  const refresh = useRefreshSkill();
  const toast = useToast();

  const [deleting, setDeleting] = useState<Skill | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const skills = data?.skills ?? [];
  const gitCount = skills.filter((s) => s.source_type === "git").length;

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return skills.filter((s) => {
      if (filter !== "all" && s.source_type !== filter) return false;
      if (!q) return true;
      return s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
    });
  }, [skills, query, filter]);

  async function onDelete(s: Skill) {
    try { await del.mutateAsync(s.id); toast.success(`Deleted ${s.name}`); setDeleting(null); }
    catch (err) { toast.error("Couldn't delete skill", err instanceof ApiError ? err.message : undefined); }
  }

  async function onRefresh(id: string) {
    try { await refresh.mutateAsync(id); toast.success("Skill re-pinned"); }
    catch (err) { toast.error("Couldn't refresh skill", err instanceof ApiError ? err.message : undefined); }
  }

  const subtitle = isLoading || skills.length === 0
    ? "Reusable instructions the opencode and codex drivers load on demand."
    : `${skills.length} skill${skills.length === 1 ? "" : "s"}` +
      (gitCount > 0 ? ` · ${gitCount} from git` : "");

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title" style={{ display: "flex", alignItems: "flex-end", gap: 12 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Skills</div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>{subtitle}</div>
        </div>
      </div>

      {/* While loading we render no "New skill" affordance, so the stable
          post-load control is the only one the user can target. */}
      {isLoading ? (
        <SkillsSkeleton />
      ) : skills.length === 0 ? (
        <EmptyHero />
      ) : (
        <>
          {/* Toolbar: search + type filter (left) · New skill (right) */}
          <div style={{ display: "flex", alignItems: "stretch", gap: 12, flexWrap: "wrap" }}>
            <div className="search-pill fluid-w" style={{ width: 320, maxWidth: "100%" }}>
              <Icons.Search />
              <input
                aria-label="Search skills"
                placeholder="Search skills…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <SegControl<Filter>
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "All" },
                { value: "inline", label: "Inline" },
                { value: "git", label: "Git" },
              ]}
            />
            <Link
              to="/settings/skills/new"
              className="btn btn-primary btn-sm"
              style={{ marginLeft: "auto", gap: 6, padding: "6px 12px 6px 10px" }}
            >
              <Icons.Plus w={14} /> New skill
            </Link>
          </div>

          {/* List */}
          <div className="card flush">
            <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={4} style={{ padding: "28px 14px", textAlign: "center", color: "var(--muted)" }}>
                      No skills match your search.
                    </td>
                  </tr>
                )}
                {visible.map((s) => {
                  const git = s.source_type === "git";
                  return (
                    <tr key={s.id}>
                      {/* Skill: glyph + name + description */}
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                          <SkillGlyph git={git} />
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontWeight: 600, fontSize: 13.5 }}>{s.name}</div>
                            <div
                              title={s.description}
                              style={{
                                fontSize: 12.5, color: "var(--muted)", marginTop: 1,
                                maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }}
                            >
                              {s.description}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Source: type + (git) repo + short sha */}
                      <td>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                          <Pill tone={git ? "info" : "brand"}>{git ? "git" : "inline"}</Pill>
                          {git && (
                            <span
                              title={s.source_url ?? undefined}
                              style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--muted)", fontFamily: "var(--font-mono)" }}
                            >
                              {s.pinned_sha && <span className="tag">{s.pinned_sha.slice(0, 7)}</span>}
                              <span style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {repoLabel(s.source_url)}
                              </span>
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Status */}
                      <td>
                        {s.enabled
                          ? <Pill tone="success"><span className="dot" />enabled</Pill>
                          : <Pill tone="dormant"><span className="dot" />disabled</Pill>}
                      </td>

                      {/* Actions */}
                      <td>
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                          {git && (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => onRefresh(s.id)}
                              disabled={refresh.isPending}
                              title="Re-fetch and re-pin to the latest commit for this ref"
                              style={{ gap: 6, padding: "6px 10px" }}
                            >
                              <Icons.Refresh w={14} /> Re-pin
                            </Button>
                          )}
                          <Link to={`/settings/skills/${s.id}/edit`} className="btn btn-secondary btn-sm">Edit</Link>
                          <Button
                            size="sm"
                            variant="danger"
                            aria-label={`Delete ${s.name}`}
                            onClick={() => setDeleting(s)}
                          >
                            <Icons.Trash w={14} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>
        </>
      )}

      <ConfirmDialog
        open={!!deleting} title="Delete skill"
        body={`Delete "${deleting?.name}"? Containers that referenced it stop loading it.`}
        confirmLabel="Delete" destructive
        onConfirm={() => deleting && onDelete(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}

function SkillsSkeleton() {
  return (
    <div className="card flush" aria-busy="true" aria-label="Loading skills">
      <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr><th>Skill</th><th>Source</th><th>Status</th><th aria-label="Actions" /></tr>
        </thead>
        <tbody>
          {[0, 1, 2].map((i) => (
            <tr key={i}>
              <td>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span className="skel" style={{ width: 34, height: 34, borderRadius: 9 }} />
                  <div style={{ display: "grid", gap: 6 }}>
                    <span className="skel" style={{ width: 130, height: 11 }} />
                    <span className="skel" style={{ width: 200, height: 10 }} />
                  </div>
                </div>
              </td>
              <td><span className="skel" style={{ width: 64, height: 18, borderRadius: 999 }} /></td>
              <td><span className="skel" style={{ width: 64, height: 18, borderRadius: 999 }} /></td>
              <td />
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function EmptyHero() {
  return (
    <div className="card" style={{ display: "grid", placeItems: "center", textAlign: "center", padding: "56px 24px", gap: 6 }}>
      <div
        aria-hidden
        style={{ width: 48, height: 48, borderRadius: 14, background: "var(--p-300)", color: "var(--ink)", display: "grid", placeItems: "center", marginBottom: 6 }}
      >
        <Icons.Puzzle w={24} />
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em" }}>No skills yet</div>
      <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 380 }}>
        Skills are reusable instructions the opencode and codex drivers load on demand. Author one
        inline, or install a published skill from a git repository.
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", justifyContent: "center" }}>
        <Link to="/settings/skills/new" className="btn btn-primary btn-sm" style={{ gap: 6, padding: "6px 12px 6px 10px" }}>
          <Icons.Plus w={14} /> New skill
        </Link>
        <Link to="/settings/skills/new?source=git" className="btn btn-secondary btn-sm" style={{ gap: 6, padding: "6px 12px 6px 10px" }}>
          <Icons.Code w={14} /> Install from git
        </Link>
      </div>
    </div>
  );
}
