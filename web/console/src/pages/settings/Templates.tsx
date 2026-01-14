import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useTemplates, keys } from "../../api/queries";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { Icons } from "../../ui/Icon";
import { EmptyState } from "../../ui/EmptyState";
import { driverIcon, driverLabel } from "../../lib/drivers";
import { isAdmin } from "../../lib/roles";
import type { Template } from "../../api/types";

export default function Templates() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const { data } = useTemplates();
  const qc = useQueryClient();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Template | null>(null);
  const [query, setQuery] = useState("");
  const templates = data?.templates ?? [];

  const match = (t: Template) =>
    t.name.toLowerCase().includes(query.toLowerCase()) || t.driver.toLowerCase().includes(query.toLowerCase());
  const builtins = templates.filter((t) => t.is_builtin && match(t));
  const tenant = templates.filter((t) => !t.is_builtin && match(t));

  async function clone(t: Template) {
    try {
      await api.post(`/v1/templates/${t.id}/clone`);
      toast.success(`Cloned ${t.name}`);
      qc.invalidateQueries({ queryKey: keys.templates });
    } catch (err) {
      toast.error("Couldn't clone template", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function del(t: Template) {
    try {
      await api.del(`/v1/templates/${t.id}`);
      toast.success(`Deleted ${t.name}`);
      qc.invalidateQueries({ queryKey: keys.templates });
      setDeleting(null);
    } catch (err) {
      toast.error("Couldn't delete template", err instanceof ApiError ? err.message : undefined);
    }
  }

  function renderCard(t: Template) {
    const toolTags = t.available_tool_specs?.slice(0, 3).map((s) => s.name) ?? [];
    const extraTools = (t.available_tool_specs?.length ?? 0) - toolTags.length;

    return (
      <div key={t.id} data-template className="card" style={{ padding: 0, overflow: "hidden" }}>
        {/* Card header */}
        <div style={{ padding: 16, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: t.is_builtin ? "var(--p-300)" : "var(--surface-3)", display: "grid", placeItems: "center", flexShrink: 0 }}>
            {(() => {
              // Built-in cards use a representative per-driver icon; custom ones keep the terminal glyph.
              const Glyph = t.is_builtin ? driverIcon(t.driver) : Icons.Terminal;
              return <Glyph w={18} />;
            })()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t.is_builtin ? t.name.replace(t.driver, driverLabel(t.driver)) : t.name}
              </span>
              {t.is_builtin && (
                <Pill tone="info" style={{ fontSize: 11, flexShrink: 0 }}>built-in</Pill>
              )}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>
              driver: {driverLabel(t.driver)}
              {t.model && <> · {t.model}</>}
            </div>
          </div>
        </div>

        {/* Card body */}
        <div style={{ padding: 16 }}>
          {toolTags.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 12 }}>
              {toolTags.map((tag) => (
                <span key={tag} className="tag" style={{ fontSize: 10.5 }}>{tag}</span>
              ))}
              {extraTools > 0 && (
                <span className="tag" style={{ fontSize: 10.5 }}>+{extraTools} more</span>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 6 }}>
            {admin && !t.is_builtin && (
              <Link to={`/settings/templates/${t.id}/edit`} className="btn btn-secondary btn-sm">Edit</Link>
            )}
            <Button variant="secondary" size="sm" onClick={() => clone(t)}>
              Clone
            </Button>
            {admin && !t.is_builtin && (
              <Button variant="danger" size="sm" onClick={() => setDeleting(t)}>
                Delete
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title">
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Templates</div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Agent configuration blueprints. Create one, or clone a built-in to start from it.
        </div>
      </div>

      {/* Toolbar: search (left) + New (right) — matches the Containers toolbar.
          align-items: stretch makes the New button match the search field's
          height (as the SegControl does on the Containers toolbar). */}
      <div style={{ display: "flex", alignItems: "stretch", gap: 12 }}>
        <div className="search-pill" style={{ width: 360, maxWidth: "100%" }}>
          <Icons.Search />
          <input
            aria-label="Search templates"
            placeholder="Search templates…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {admin && (
          <Link
            to="/settings/templates/new"
            className="btn btn-primary btn-sm"
            style={{ marginLeft: "auto", gap: 6, padding: "6px 12px 6px 10px" }}
          >
            <Icons.Plus /> New template
          </Link>
        )}
      </div>

      {builtins.length > 0 && (
        <section>
          <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)", marginBottom: 10 }}>
            Built-in
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
            {builtins.map((t) => renderCard(t))}
          </div>
        </section>
      )}

      {tenant.length > 0 && (
        <section>
          <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)", marginBottom: 10 }}>
            Your templates
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
            {tenant.map((t) => renderCard(t))}
          </div>
        </section>
      )}

      {builtins.length === 0 && tenant.length === 0 && (
        query ? (
          <div className="note">No templates match your search.</div>
        ) : (
          <EmptyState
            icon="Templates"
            title="No templates yet"
            description="Templates capture a reusable driver, model and skill setup for new containers."
            actions={
              <Link to="/settings/templates/new" className="btn btn-primary btn-sm">
                <Icons.Plus w={14} /> New template
              </Link>
            }
          />
        )
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete template"
        body={`Delete "${deleting?.name}"? Containers already created from it keep their config.`}
        confirmLabel="Delete"
        onConfirm={() => deleting && del(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
