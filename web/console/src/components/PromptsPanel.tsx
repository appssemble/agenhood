import { Link } from "react-router-dom";
import { Icons } from "../ui/Icon";
import { EmptyState } from "../ui/EmptyState";
import { extractVariables } from "../lib/prompts";
import { relativeFromNow } from "../lib/format";
import type { Prompt } from "../api/types";

const MAX_ROWS = 4;
const MAX_TAGS = 2;

export function PromptsPanel({ prompts }: { prompts: Prompt[] }) {
  const total = prompts.length;
  const rows = [...prompts]
    .sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1))
    .slice(0, MAX_ROWS);

  return (
    <div>
      <div className="panel-head">
        <span className="panel-title">Prompts</span>
        {total > 0 && <span className="count-chip">{total}</span>}
        <Link to="/prompts" className="panel-link">
          {total > 0 ? "View all" : "Open"} <Icons.ArrowRight w={13} />
        </Link>
      </div>

      {total === 0 ? (
        <EmptyState
          size="sm"
          icon="Prompt"
          title="No prompts yet"
          description="Save a reusable prompt with {{variables}} to drop into any task."
          actions={<Link to="/prompts/new" className="btn btn-primary btn-sm"><Icons.Plus w={14} /> New prompt</Link>}
        />
      ) : (
        <div>
          {rows.map((p) => {
            const varCount = extractVariables(p.body).length;
            const tags = p.tags.slice(0, MAX_TAGS);
            const extraTags = p.tags.length - tags.length;
            return (
              <Link key={p.id} to={`/prompts/${p.id}/edit`} className="dash-row" title={p.name}>
                <div className="dash-ico"><Icons.Prompt w={15} /></div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="row-name">{p.name}</div>
                  <div className="row-meta">
                    <span>{varCount} var{varCount === 1 ? "" : "s"}</span>
                    <span style={{ color: "var(--muted-2)" }}>· {relativeFromNow(p.updated_at, Date.now())}</span>
                  </div>
                </div>
                {p.tags.length > 0 && (
                  <div style={{ display: "flex", gap: 5, alignItems: "center", flexShrink: 0 }}>
                    {tags.map((t) => (
                      <span key={t} className="tag" title={t} style={{ display: "inline-block", fontSize: 10.5, maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t}</span>
                    ))}
                    {extraTags > 0 && <span style={{ fontSize: 10.5, color: "var(--muted-2)", fontWeight: 600 }}>+{extraTags}</span>}
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
