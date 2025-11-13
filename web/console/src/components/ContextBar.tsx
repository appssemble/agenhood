// web/console/src/components/ContextBar.tsx
import { useNavigate } from "react-router-dom";
import { Breadcrumbs } from "./Breadcrumbs";
import type { Crumb } from "../lib/crumbs";
import { Icons } from "../ui/Icon";
import { ApiActivityButton } from "./ApiActivityPanel";
import { TenantSwitcher } from "./TenantSwitcher";

export function ContextBar({ crumbs, runningCount, onOpenPalette, onToggleApiLog, apiLogOpen, onToggleNav }: {
  crumbs: Crumb[]; runningCount: number; onOpenPalette: () => void; onToggleApiLog: () => void; apiLogOpen: boolean; onToggleNav: () => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="fc-ctxbar">
      <button type="button" className="fc-hamburger" aria-label="Open navigation" onClick={onToggleNav}>
        <Icons.Menu />
      </button>
      <Breadcrumbs items={crumbs} />
      <div className="fc-ctxbar-center">
        <TenantSwitcher />
        <button
          type="button"
          onClick={onOpenPalette}
          aria-label="Jump to container, task, command"
          className="searchbox"
        >
          <Icons.Search />
          <span>Jump to container, task, command…</span>
          <kbd>⌘K</kbd>
        </button>
      </div>
      <div className="fc-ctxbar-right">
        {runningCount > 0 && (
          <button type="button" className="fc-run" aria-label={`${runningCount} running`} onClick={() => navigate("/tasks")}>
            <span className="dot" /> {runningCount} running
          </button>
        )}
        <ApiActivityButton onClick={onToggleApiLog} active={apiLogOpen} />
      </div>
    </div>
  );
}
