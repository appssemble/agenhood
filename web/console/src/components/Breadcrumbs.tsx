import { Link } from "react-router-dom";
import type { Crumb } from "../lib/crumbs";

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <div className="fc-crumb text-[12.5px] text-muted">
      {items.map((c, i) => (
        <span key={i}>
          {i > 0 && <span className="px-1.5 text-muted-2">/</span>}
          {c.bold ? (
            <b className="font-semibold text-ink">{c.label}</b>
          ) : c.to ? (
            <Link to={c.to}>{c.label}</Link>
          ) : (
            <span>{c.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}
