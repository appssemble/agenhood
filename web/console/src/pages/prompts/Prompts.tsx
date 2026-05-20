import { useMemo, useState, useRef, useLayoutEffect, type ReactNode, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { usePrompts, useDeletePrompt, useWorkflows } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Icons } from "../../ui/Icon";
import { EmptyState } from "../../ui/EmptyState";
import { CopyId } from "../../ui/CopyId";
import { extractVariables } from "../../lib/prompts";
import { shortId, formatDate } from "../../lib/format";
import type { Prompt, Workflow } from "../../api/types";

// Single-line row of chips with a "+N" overflow pill. The pill carries a
// tooltip listing the hidden items, so nothing is lost when there are many.
const OVERFLOW_PILL: CSSProperties = {
  flexShrink: 0,
  fontSize: 10.5,
  fontWeight: 600,
  color: "var(--muted-2)",
  background: "var(--surface-3)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "2px 7px",
  cursor: "default",
};

function ChipRow({
  label,
  items,
  max,
  render,
}: {
  label?: string;
  items: string[];
  max: number;
  render: (item: string) => ReactNode;
}) {
  if (items.length === 0) return null;
  const shown = items.slice(0, max);
  const hidden = items.slice(max);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
      {label && (
        <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--muted-2)", flexShrink: 0 }}>
          {label}
        </span>
      )}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", minWidth: 0, flex: 1 }}>
        {shown.map(render)}
        {hidden.length > 0 && (
          <span title={hidden.join(", ")} style={OVERFLOW_PILL}>+{hidden.length}</span>
        )}
      </div>
    </div>
  );
}

// display:inline-block (not the chips' default inline-flex) is required for
// text-overflow:ellipsis to render — ellipsis doesn't apply to flex containers.
const CHIP_ELLIPSIS: CSSProperties = { display: "inline-block", maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 };

const PREVIEW_LINE = 18;   // px, matches lineHeight below
const PREVIEW_PAD = 20;    // px, vertical padding (10 top + 10 bottom)
const PREVIEW_MIN_LINES = 3;

// Body preview that fills the card's available height: the card stretches to
// the tallest in its grid row, and this region grows to use the slack, showing
// as many whole lines as fit (clean -webkit-line-clamp ellipsis, no partial
// line). Padding lives on the wrapper so clamped lines can't bleed into it.
function PromptPreview({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState(PREVIEW_MIN_LINES);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const compute = () => {
      const avail = el.clientHeight - PREVIEW_PAD;
      const n = Math.max(PREVIEW_MIN_LINES, Math.floor(avail / PREVIEW_LINE));
      setLines((prev) => (prev === n ? prev : n));
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      title={text || undefined}
      style={{ flex: "1 1 auto", minHeight: PREVIEW_MIN_LINES * PREVIEW_LINE + PREVIEW_PAD, background: "var(--surface-2)", borderRadius: 8, padding: "10px 12px", overflow: "hidden" }}
    >
      <div
        style={{
          display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: lines,
          overflow: "hidden", overflowWrap: "anywhere",
          fontSize: 12, lineHeight: `${PREVIEW_LINE}px`, color: "var(--ink-2)", whiteSpace: "pre-wrap",
        }}
      >
        {text || <span style={{ color: "var(--muted-2)" }}>Empty prompt</span>}
      </div>
    </div>
  );
}

export default function Prompts() {
  const { data, isLoading } = usePrompts();
  const del = useDeletePrompt();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Prompt | null>(null);
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState<string | null>(null);

  const prompts = data?.prompts ?? [];
  const workflows: Workflow[] = useWorkflows().data?.workflows ?? [];

  // How many workflows reference each prompt (counted once per workflow).
  const usage = useMemo(() => {
    const m = new Map<string, number>();
    workflows.forEach((w) => {
      new Set(w.steps.map((s) => s.prompt_id)).forEach((pid) => m.set(pid, (m.get(pid) ?? 0) + 1));
    });
    return m;
  }, [workflows]);

  const allTags = useMemo(() => {
    const s = new Set<string>();
    prompts.forEach((p) => p.tags.forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [prompts]);

  // How many prompts carry each tag — shown as a count on the filter chips.
  const tagCounts = useMemo(() => {
    const m = new Map<string, number>();
    prompts.forEach((p) => p.tags.forEach((t) => m.set(t, (m.get(t) ?? 0) + 1)));
    return m;
  }, [prompts]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return prompts.filter((p) => {
      const matchesQ = !q || p.name.toLowerCase().includes(q) || p.body.toLowerCase().includes(q);
      const matchesTag = !tag || p.tags.includes(tag);
      return matchesQ && matchesTag;
    });
  }, [prompts, query, tag]);

  async function onDelete(p: Prompt) {
    try {
      await del.mutateAsync(p.id);
      toast.success(`Deleted ${p.name}`);
      setDeleting(null);
    } catch (err) {
      toast.error("Couldn't delete prompt", err instanceof ApiError ? err.message : undefined);
    }
  }

  function renderCard(p: Prompt) {
    const vars = extractVariables(p.body);
    const used = usage.get(p.id) ?? 0;
    // Keep the prompt's line breaks (so the preview reads like the prompt) but
    // drop blank lines so they don't waste the 3-line budget.
    const preview = p.body.trim().replace(/[ \t]+$/gm, "").replace(/\n{2,}/g, "\n");
    return (
      <div key={p.id} className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        {/* header: icon + name + short id */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: "var(--p-100)", border: "1px solid rgba(135,130,13,.2)", display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Icons.Prompt w={16} />
          </div>
          <div style={{ minWidth: 0, flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ minWidth: 0, flex: 1, fontSize: 14.5, fontWeight: 700, letterSpacing: "-0.01em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {p.name}
            </div>
            <div style={{ flexShrink: 0 }}><CopyId id={p.id} label={shortId(p.id)} /></div>
          </div>
        </div>

        {/* body preview — grows to fill the card's spare height */}
        <PromptPreview text={preview} />

        {/* variables — distinct from tags */}
        <ChipRow
          label="Vars"
          items={vars}
          max={4}
          render={(v) => (
            <span key={v} className="mono" title={`{{${v}}}`} style={{ fontSize: 10.5, fontWeight: 600, color: "var(--p-700)", background: "var(--p-100)", border: "1px solid rgba(135,130,13,.22)", borderRadius: 6, padding: "2px 7px", ...CHIP_ELLIPSIS }}>
              {`{{${v}}}`}
            </span>
          )}
        />

        {/* tags */}
        <ChipRow
          items={p.tags}
          max={4}
          render={(t) => <span key={t} className="tag" title={t} style={{ fontSize: 10.5, ...CHIP_ELLIPSIS }}>{t}</span>}
        />

        {/* meta: usage + updated */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)" }}>
          <Icons.Workflow w={12} />
          <span>{used === 0 ? "Not used in a workflow" : `Used in ${used} workflow${used === 1 ? "" : "s"}`}</span>
          <span style={{ color: "var(--muted-2)" }}>· Updated {formatDate(p.updated_at)}</span>
        </div>

        {/* actions */}
        <div className="card-actions">
          <Link to={`/prompts/${p.id}/edit`} className="btn btn-ghost btn-sm"><Icons.Pencil w={14} /> Edit</Link>
          <Link to={`/schedules/new?kind=prompt&prompt_id=${p.id}`} className="btn btn-ghost btn-sm"><Icons.Clock w={14} /> Schedule</Link>
          <Button variant="danger" size="sm" className="danger-sep" aria-label={`Delete ${p.name}`} onClick={() => setDeleting(p)}>
            <Icons.Trash w={14} /> Delete
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Prompts</div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Reusable prompts for tasks, workflows &amp; scheduled runs. Shared across your workspace.
        </div>
      </div>

      {!isLoading && prompts.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* row 1: search + primary action */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div className="search-pill" style={{ flex: "1 1 280px", maxWidth: 440 }}>
              <Icons.Search />
              <input aria-label="Search prompts" placeholder="Search prompts…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            <Link to="/prompts/new" className="btn btn-primary btn-sm" style={{ marginLeft: "auto", gap: 6, padding: "6px 12px 6px 10px" }}>
              <Icons.Plus w={14} /> New prompt
            </Link>
          </div>

          {/* row 2: tag filters */}
          {allTags.length > 0 && (
            <div className="filter-row">
              <span className="filter-label"><Icons.Filter w={13} /> Filter</span>
              <button className={"filter-chip" + (tag === null ? " active" : "")} aria-pressed={tag === null} onClick={() => setTag(null)}>
                All <span className="count">{prompts.length}</span>
              </button>
              {allTags.map((t) => (
                <button key={t} className={"filter-chip" + (tag === t ? " active" : "")} aria-pressed={tag === t} onClick={() => setTag(t)}>
                  {t} <span className="count">{tagCounts.get(t) ?? 0}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="note">Loading…</div>
      ) : prompts.length === 0 ? (
        <EmptyState
          icon="Prompt"
          title="No prompts yet"
          description="Create a reusable prompt with {{variables}} you can drop into any task."
          actions={<Link to="/prompts/new" className="btn btn-primary btn-sm"><Icons.Plus w={14} /> New prompt</Link>}
        />
      ) : visible.length === 0 ? (
        <div className="note">No prompts match your filters.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {visible.map(renderCard)}
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete prompt"
        body={`Delete "${deleting?.name}"? This can't be undone. Tasks already created from it are unaffected.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleting && onDelete(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
