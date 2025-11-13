import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Container } from "../api/types";
import { usePins } from "../lib/pins";
import { sortByRecency } from "../lib/recents";
import { Icons } from "../ui/Icon";

function dotClass(status: string) {
  if (status === "running") return "fc-cdot running";
  if (status === "error") return "fc-cdot error";
  if (status === "archived") return "fc-cdot archived";
  return "fc-cdot";
}

export function ContainerSwitcher({ containers, activeId }: { containers: Container[]; activeId: string }) {
  const navigate = useNavigate();
  const { pins } = usePins();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const active = containers.find((c) => c.id === activeId);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on click/tap outside the switcher, or on Escape.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = useMemo(() => {
    const s = q.trim().toLowerCase();
    const match = (c: Container) =>
      !s || c.name.toLowerCase().includes(s) || (c.external_id ?? c.id).toLowerCase().includes(s);
    const all = containers.filter(match);
    const pinned = all.filter((c) => pins.includes(c.id));
    const recent = sortByRecency(all.filter((c) => !pins.includes(c.id))).slice(0, 6);
    return [
      { label: "Pinned", items: pinned },
      { label: "Recent", items: recent },
    ].filter((g) => g.items.length > 0);
  }, [containers, pins, q]);

  function choose(c: Container) {
    setOpen(false);
    setQ("");
    navigate(`/containers/${c.id}`);
  }

  return (
    <div className="fc-switcher" ref={rootRef}>
      <button
        type="button"
        className="fc-sw-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={dotClass(active?.status ?? "")} />
        <span className="fc-sw-txt">
          <span className="fc-sw-name" title={active?.name ?? undefined}>{active?.name ?? "Select container"}</span>
          {active && (
            <span className="id" title={active.external_id ?? active.id}>{active.external_id ?? active.id}</span>
          )}
        </span>
        <Icons.ArrowDown className="chev icon" />
      </button>
      {open && (
        <div className="fc-sw-pop" role="listbox">
          <div className="fc-search">
            <Icons.Search />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Switch container…"
            />
          </div>
          {groups.map((g) => (
            <div key={g.label}>
              <div className="fc-glab">{g.label}</div>
              {g.items.map((c) => (
                <div
                  key={c.id}
                  role="option"
                  aria-selected={c.id === activeId}
                  className={"fc-sw-item" + (c.id === activeId ? " cur" : "")}
                  onClick={() => choose(c)}
                >
                  <span className={dotClass(c.status)} />
                  <span className="fc-sw-iname" title={c.name}>{c.name}</span>
                  <span className="id" title={c.external_id ?? c.id}>{c.external_id ?? c.id}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
