import { useMemo } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import type { Container, Me } from "../api/types";
import { useTenantTasks } from "../api/queries";
import { usePins } from "../lib/pins";
import { sortByRecency } from "../lib/recents";
import { isAdmin } from "../lib/roles";
import { Icons } from "../ui/Icon";

function dotClass(status: string) {
  if (status === "running") return "fc-cdot running";
  if (status === "error") return "fc-cdot error";
  if (status === "archived") return "fc-cdot archived";
  return "fc-cdot";
}
const navCls = ({ isActive }: { isActive: boolean }) => "fc-nav" + (isActive ? " active" : "");

export function FleetPanel({ containers, user }: { containers: Container[]; user: Me }) {
  const navigate = useNavigate();
  const { pins } = usePins();
  const admin = isAdmin(user);
  const tasks = useTenantTasks().data?.tasks ?? [];

  const runningByContainer = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of tasks) if (t.status === "running" && !m.has(t.container_id)) m.set(t.container_id, t.task_id);
    return m;
  }, [tasks]);

  const groups = useMemo(() => {
    const pinned = containers.filter((c) => pins.includes(c.id));
    const recent = sortByRecency(containers.filter((c) => !pins.includes(c.id)));
    return [
      { label: "Pinned", items: pinned },
      { label: "Recent", items: recent },
    ].filter((g) => g.items.length > 0);
  }, [containers, pins]);

  return (
    <nav className="fc-panel" aria-label="Fleet navigation">
      <div className="fc-panel-head">Fleet</div>
      <div className="fc-plist">
        <NavLink to="/settings/templates" className={navCls}><Icons.Templates /> Templates</NavLink>
        {admin && <NavLink to="/settings/skills" className={navCls}><Icons.Puzzle /> Skills</NavLink>}
        {admin && <NavLink to="/settings/mcp" className={navCls}><Icons.Web /> MCP servers</NavLink>}
        <NavLink to="/containers" className={navCls}>
          <Icons.Container /> <span>Containers</span>
          <span className="badge">{containers.length}</span>
        </NavLink>

        {groups.map((g) => (
          <div key={g.label}>
            <div className="fc-glab">{g.label}</div>
            {g.items.map((c) => {
              const runningTid = runningByContainer.get(c.id);
              return (
                <NavLink key={c.id} to={`/containers/${c.id}`} className={navCls}>
                  <span className={dotClass(c.status)} />
                  <span>{c.name}</span>
                  {runningTid && (
                    <button
                      type="button"
                      className="fc-livechip"
                      aria-label={`Watch running task on ${c.name}`}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        navigate(`/containers/${c.id}/tasks/${runningTid}`);
                      }}
                    >
                      <span className="dot" /> live
                    </button>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}
