import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { useAllTenants, useSelectTenant } from "../api/queries";
import { Icons } from "../ui/Icon";
import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";

type Opt = { id: string; name: string; role?: string };

export function TenantSwitcher() {
  const { user } = useAuth();
  const select = useSelectTenant();
  const isStaff = !!user?.is_staff;
  const allTenants = useAllTenants(isStaff);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

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
  useEffect(() => { if (!open) setQ(""); }, [open]);
  // The switcher lives in the persistent header, so its open state survives
  // route changes. Dismiss the menu and the create dialog when the user
  // navigates (e.g. via the left rail) so neither lingers over a new screen.
  useEffect(() => { setOpen(false); setShowCreate(false); }, [pathname]);

  // Workspaces the user owns/belongs to (members: their memberships; staff: the
  // workspaces they own). Staff additionally get every other tenant to impersonate.
  const owned: Opt[] = useMemo(
    () => (user?.tenants ?? []).map((t) => ({ id: t.id, name: t.name, role: t.role })),
    [user?.tenants],
  );
  const ownedIds = useMemo(() => new Set(owned.map((o) => o.id)), [owned]);
  const others: Opt[] = useMemo(
    () =>
      isStaff
        ? (allTenants.data?.tenants ?? [])
            .filter((t) => !ownedIds.has(t.id))
            .map((t) => ({ id: t.id, name: t.name }))
        : [],
    [isStaff, allTenants.data, ownedIds],
  );

  const matches = (name: string) =>
    !q.trim() || name.toLowerCase().includes(q.trim().toLowerCase());
  const ownedF = owned.filter((o) => matches(o.name));
  const othersF = others.filter((o) => matches(o.name));
  const showSearch = owned.length + others.length > 8;

  if (!user) return null;

  const activeId = user.active_tenant_id;
  const ownedActive = owned.find((o) => o.id === activeId);
  let label: string;
  if (isStaff) {
    if (ownedActive) label = ownedActive.name;
    else if (activeId)
      label = `Impersonating: ${others.find((o) => o.id === activeId)?.name ?? "…"}`;
    else label = "Select workspace";
  } else {
    label = ownedActive?.name ?? user.tenant?.name ?? "Select workspace";
  }

  async function choose(tenantId: string | null) {
    setOpen(false);
    setQ("");
    await select.mutateAsync(tenantId);
  }

  const optionRow = (o: Opt) => (
    <li
      key={o.id}
      role="option"
      aria-selected={o.id === activeId}
      className={"dd-option" + (o.id === activeId ? " selected" : "")}
      onMouseDown={(e) => { e.preventDefault(); choose(o.id); }}
    >
      <span>{o.name}</span>
      {o.role ? <span className="chip">{o.role}</span> : null}
    </li>
  );

  return (
    <>
      <div className="dd tenant-switcher" ref={rootRef}>
        <button
          type="button"
          className={"select dd-trigger tenant-trigger" + (open ? " open" : "")}
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <span>{label}</span>
        </button>
        {open && (
          <div className="dd-menu">
            {showSearch && (
              <div className="dd-search">
                <Icons.Search w={14} />
                <input
                  type="text"
                  placeholder="Search workspaces…"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  aria-label="Search workspaces"
                  autoFocus
                />
              </div>
            )}
            <ul className="dd-list" role="listbox">
              {isStaff ? (
                <>
                  {ownedF.length > 0 && <li className="dd-group" aria-hidden="true">Your workspaces</li>}
                  {ownedF.map(optionRow)}
                  {othersF.length > 0 && <li className="dd-group" aria-hidden="true">All workspaces</li>}
                  {othersF.map(optionRow)}
                  {ownedF.length === 0 && othersF.length === 0 && (
                    <li className="dd-empty">No matches</li>
                  )}
                </>
              ) : ownedF.length === 0 ? (
                <li className="dd-empty">No matches</li>
              ) : (
                ownedF.map(optionRow)
              )}
              <li
                role="option"
                aria-selected={false}
                className="dd-option dd-action"
                onMouseDown={(e) => { e.preventDefault(); setOpen(false); setShowCreate(true); }}
              >
                <span className="dd-action-plus" aria-hidden="true">+</span>
                <span>New workspace</span>
              </li>
            </ul>
          </div>
        )}
      </div>
      <CreateWorkspaceDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(id) => { void select.mutateAsync(id); }}
      />
    </>
  );
}
