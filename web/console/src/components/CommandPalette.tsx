import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Container, Template } from "../api/types";
import { buildItems, filterItems, type CommandItem } from "./commandItems";
import { Icons } from "../ui/Icon";

function itemIcon(item: CommandItem) {
  if (item.kind === "container") return <Icons.Container />;
  if (item.kind === "template") return <Icons.Templates />;
  // action items
  if (item.label === "New container") return <Icons.Plus />;
  return <Icons.Arrow />;
}

export function CommandPalette({ open, onClose, containers, templates }: {
  open: boolean; onClose: () => void; containers: Container[]; templates: Template[];
}) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const items = useMemo(() => filterItems(buildItems(containers, templates), q), [containers, templates, q]);

  useEffect(() => { if (open) { setQ(""); setActive(0); } }, [open]);
  useEffect(() => { setActive(0); }, [q]);

  if (!open) return null;

  const go = (item?: CommandItem) => { if (item) navigate(item.to); onClose(); };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[active]); }
  };

  // Group items by kind for palette-group headers
  const containerItems = items.filter((i) => i.kind === "container");
  const templateItems = items.filter((i) => i.kind === "template");
  const actionItems = items.filter((i) => i.kind === "action");

  return (
    <div className="palette-scrim" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <div className="palette-input">
          <Icons.Search />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to container, task, command…"
          />
          <kbd>esc</kbd>
        </div>
        <div className="palette-list">
          {items.length === 0 && (
            <div style={{ padding: "24px 10px", textAlign: "center", fontSize: 13, color: "var(--muted)" }}>
              No matches
            </div>
          )}
          {containerItems.length > 0 && (
            <>
              <div className="palette-group">Containers</div>
              {containerItems.map((it) => {
                const globalIdx = items.indexOf(it);
                return (
                  <div
                    key={globalIdx}
                    className={"palette-item" + (globalIdx === active ? " active" : "")}
                    onClick={() => go(it)}
                    onMouseEnter={() => setActive(globalIdx)}
                  >
                    <div className="icobox">{itemIcon(it)}</div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{it.label}</div>
                      <div className="id" style={{ fontSize: 11 }}>{it.sub}</div>
                    </div>
                    <span className="meta">jump</span>
                  </div>
                );
              })}
            </>
          )}
          {templateItems.length > 0 && (
            <>
              <div className="palette-group">Templates</div>
              {templateItems.map((it) => {
                const globalIdx = items.indexOf(it);
                return (
                  <div
                    key={globalIdx}
                    className={"palette-item" + (globalIdx === active ? " active" : "")}
                    onClick={() => go(it)}
                    onMouseEnter={() => setActive(globalIdx)}
                  >
                    <div className="icobox">{itemIcon(it)}</div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{it.label}</div>
                      <div className="id" style={{ fontSize: 11 }}>{it.sub}</div>
                    </div>
                    <span className="meta">open</span>
                  </div>
                );
              })}
            </>
          )}
          {actionItems.length > 0 && (
            <>
              <div className="palette-group">Actions</div>
              {actionItems.map((it) => {
                const globalIdx = items.indexOf(it);
                return (
                  <div
                    key={globalIdx}
                    className={"palette-item" + (globalIdx === active ? " active" : "")}
                    onClick={() => go(it)}
                    onMouseEnter={() => setActive(globalIdx)}
                  >
                    <div className="icobox">{itemIcon(it)}</div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{it.label}</div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{it.sub}</div>
                    </div>
                    <span className="meta">action</span>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
