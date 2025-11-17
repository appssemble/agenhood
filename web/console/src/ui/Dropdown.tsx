import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icons } from "./Icon";

export type DropdownOption = { value: string; label: string; disabled?: boolean };

export function Dropdown({
  value,
  onChange,
  options,
  id,
  placeholder = "Select…",
  disabled = false,
  searchable,
  width,
  className = "",
  portal = false,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: DropdownOption[];
  id?: string;
  placeholder?: string;
  disabled?: boolean;
  searchable?: boolean;
  width?: number | string;
  className?: string;
  /** Render the menu in a body portal (fixed position) so it escapes clipping/scroll ancestors. */
  portal?: boolean;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [query, setQuery] = useState("");
  const [up, setUp] = useState(false);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});
  const [listMaxH, setListMaxH] = useState<number | undefined>(undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const typeahead = useRef<{ buf: string; t: number }>({ buf: "", t: 0 });

  const reactId = useId();
  const baseId = id ?? reactId;
  const listId = `${baseId}-list`;
  const optId = (i: number) => `${baseId}-opt-${i}`;

  const selected = options.find((o) => o.value === value);
  const showSearch = searchable ?? options.length > 8;

  const filtered = useMemo(() => {
    if (!showSearch || !query.trim()) return options;
    const q = query.trim().toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(q));
  }, [options, query, showSearch]);

  function firstEnabled(list: DropdownOption[]): number {
    const i = list.findIndex((o) => !o.disabled);
    return i < 0 ? 0 : i;
  }
  function lastEnabled(list: DropdownOption[]): number {
    for (let i = list.length - 1; i >= 0; i--) if (!list[i].disabled) return i;
    return 0;
  }
  function step(from: number, dir: 1 | -1): number {
    let i = from + dir;
    while (i >= 0 && i < filtered.length) {
      if (!filtered[i].disabled) return i;
      i += dir;
    }
    return from; // no enabled option that direction; stay put
  }

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  // Close on outside click (no focus restore — focus follows the click). The
  // portaled menu lives outside rootRef, so it must be excluded explicitly.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t)) return;
      if (menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Portal mode: anchor the fixed-position menu to the trigger, flipping up when
  // there isn't room below. Recompute on scroll/resize while open.
  useLayoutEffect(() => {
    if (!open || !portal) return;
    const place = () => {
      const t = triggerRef.current;
      if (!t) return;
      const r = t.getBoundingClientRect();
      const gap = 6;
      const below = window.innerHeight - r.bottom;
      const above = r.top;
      const flipUp = below < 280 && above > below;
      const avail = (flipUp ? above : below) - gap - 8;
      setUp(flipUp);
      setListMaxH(Math.max(120, Math.min(260, avail - 44)));
      setMenuStyle({
        position: "fixed",
        left: Math.round(r.left),
        width: Math.round(r.width),
        zIndex: 1000,
        ...(flipUp
          ? { bottom: Math.round(window.innerHeight - r.top + gap) }
          : { top: Math.round(r.bottom + gap) }),
      });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, portal]);

  // Reset the filter whenever the menu closes, so the next open starts clean
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  // On open: highlight the current value and decide flip direction
  useLayoutEffect(() => {
    if (!open) return;
    const i = options.findIndex((o) => o.value === value);
    setActive(i < 0 ? firstEnabled(options) : i);
    const r = rootRef.current?.getBoundingClientRect();
    if (r) {
      const below = window.innerHeight - r.bottom;
      setUp(below < 280 && r.top > below);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus the search box when it appears
  useEffect(() => {
    if (open && showSearch) searchRef.current?.focus();
  }, [open, showSearch]);

  // When the filter text changes (including clearing it), highlight the first match
  useEffect(() => {
    if (open) setActive(firstEnabled(filtered));
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the active option scrolled into view
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function choose(o: DropdownOption | undefined) {
    if (!o || o.disabled) return;
    onChange(o.value);
    close();
  }

  function typeJump(ch: string) {
    const now = Date.now();
    const ta = typeahead.current;
    ta.buf = now - ta.t > 600 ? ch : ta.buf + ch;
    ta.t = now;
    const i = filtered.findIndex(
      (o) => !o.disabled && o.label.toLowerCase().startsWith(ta.buf.toLowerCase()),
    );
    if (i >= 0) setActive(i);
  }

  function onKey(e: React.KeyboardEvent) {
    if (disabled) return;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) setOpen(true);
        else setActive((a) => step(a, 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        if (!open) setOpen(true);
        else setActive((a) => step(a, -1));
        break;
      case "Home":
        // Inside the filter box this overrides caret-to-start; acceptable for a short field.
        if (open) { e.preventDefault(); setActive(firstEnabled(filtered)); }
        break;
      case "End":
        if (open) { e.preventDefault(); setActive(lastEnabled(filtered)); }
        break;
      case "Enter":
        e.preventDefault();
        if (!open) setOpen(true);
        else choose(filtered[active]);
        break;
      case " ":
        // When searching, let the space reach the input.
        if (!showSearch || !open) {
          e.preventDefault();
          if (!open) setOpen(true);
          else choose(filtered[active]);
        }
        break;
      case "Escape":
        if (open) { e.preventDefault(); close(); }
        break;
      default:
        // Type-ahead jump for non-searchable lists only.
        if (!showSearch && open && e.key.length === 1) typeJump(e.key);
        break;
    }
  }

  return (
    <div
      className={("dd " + className).trim()}
      ref={rootRef}
      style={width != null ? { width } : undefined}
    >
      <button
        type="button"
        id={id}
        ref={triggerRef}
        className={"select dd-trigger" + (open ? " open" : "")}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && !showSearch && filtered[active] ? optId(active) : undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={onKey}
      >
        <span className={selected ? undefined : "dd-placeholder"}>
          {selected ? selected.label : placeholder}
        </span>
      </button>
      {open && (() => {
        const menu = (
        <div
          ref={menuRef}
          className={"dd-menu" + (up ? " up" : "")}
          style={portal ? menuStyle : undefined}
        >
          {showSearch && (
            <div className="dd-search">
              <Icons.Search w={14} />
              <input
                ref={searchRef}
                type="text"
                role="combobox"
                aria-expanded
                aria-controls={listId}
                aria-activedescendant={filtered[active] ? optId(active) : undefined}
                aria-label="Filter options"
                placeholder="Filter…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKey}
              />
            </div>
          )}
          <ul
            className="dd-list"
            id={listId}
            role="listbox"
            tabIndex={-1}
            ref={listRef}
            style={portal && listMaxH != null ? { maxHeight: listMaxH } : undefined}
          >
            {filtered.length === 0 ? (
              <li className="dd-empty">No matches</li>
            ) : (
              filtered.map((o, i) => (
                <li
                  key={o.value}
                  id={optId(i)}
                  data-idx={i}
                  role="option"
                  aria-selected={o.value === value}
                  aria-disabled={o.disabled || undefined}
                  className={
                    "dd-option" +
                    (i === active ? " active" : "") +
                    (o.value === value ? " selected" : "") +
                    (o.disabled ? " disabled" : "")
                  }
                  onMouseEnter={() => !o.disabled && setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(o);
                  }}
                >
                  <span>{o.label}</span>
                  {o.value === value && <Icons.Check w={14} />}
                </li>
              ))
            )}
          </ul>
        </div>
        );
        return portal ? createPortal(menu, document.body) : menu;
      })()}
    </div>
  );
}
