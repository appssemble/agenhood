import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { useContainers, useTemplates, useTenantTasks, useWorkflows } from "../api/queries";
import { Rail } from "./Rail";
import { Panel } from "./Panel";
import { ContextBar } from "./ContextBar";
import { CommandPalette } from "./CommandPalette";
import { ApiActivityPanel } from "./ApiActivityPanel";
import { Icons } from "../ui/Icon";
import { deriveNav } from "../lib/navSection";
import { buildCrumbs } from "../lib/crumbs";

export function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const containers = useContainers().data?.containers ?? [];
  const templates = useTemplates().data?.templates ?? [];
  const tenantTasks = useTenantTasks().data?.tasks ?? [];
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [apiLogOpen, setApiLogOpen] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  // Close the mobile nav drawer whenever the route changes.
  useEffect(() => { setNavOpen(false); }, [location.pathname]);

  const workflows = useWorkflows().data?.workflows ?? [];

  const nav = deriveNav(location.pathname);
  const activeContainer = nav.cid ? containers.find((c) => c.id === nav.cid) ?? null : null;
  // The workflow details hub is /workflows/:id exactly (not /new, /edit or /runs).
  const wfMatch = location.pathname.match(/^\/workflows\/([^/]+)$/);
  const activeWorkflow =
    wfMatch && wfMatch[1] !== "new" ? workflows.find((w) => w.id === wfMatch[1]) ?? null : null;
  const crumbs = buildCrumbs(location.pathname, activeContainer?.name, nav.cid, activeWorkflow?.name);
  const runningCount = tenantTasks.filter((t) => t.status === "running").length;

  // The secondary side panel applies to the Fleet, Workflows, Settings and Staff
  // sections; Dashboard / Tasks / Profile run full-width with just the rail.
  const sectionHasPanel =
    nav.rail === "fleet" || nav.rail === "workflows" || nav.rail === "settings" || nav.rail === "staff";
  const showPanel = sectionHasPanel && !panelCollapsed;

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  if (!user) return null;

  return (
    <div className={"fc-shell" + (showPanel ? "" : " no-panel") + (apiLogOpen ? " apilog-open" : "") + (navOpen ? " nav-open" : "")}>
      <Rail user={user} section={nav.rail} />
      {showPanel && <Panel mode={nav.panel} user={user} containers={containers} cid={nav.cid} />}
      <div className="fc-nav-scrim" onClick={() => setNavOpen(false)} />
      <div className="fc-main">
        <ContextBar
          crumbs={crumbs}
          runningCount={runningCount}
          onOpenPalette={() => setPaletteOpen(true)}
          onToggleApiLog={() => setApiLogOpen((o) => !o)}
          apiLogOpen={apiLogOpen}
          onToggleNav={() => setNavOpen((o) => !o)}
        />
        <div className="fc-scroll">
          <Outlet />
        </div>
      </div>
      {sectionHasPanel && (
        <button
          type="button"
          className={"fc-edge-toggle" + (showPanel ? " open" : "")}
          aria-label={showPanel ? "Collapse panel" : "Expand panel"}
          onClick={() => setPanelCollapsed((c) => !c)}
        >
          <Icons.ArrowRight />
        </button>
      )}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} containers={containers} templates={templates} />
      <ApiActivityPanel open={apiLogOpen} onClose={() => setApiLogOpen(false)} />
    </div>
  );
}
