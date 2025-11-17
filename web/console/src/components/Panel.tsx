import { NavLink } from "react-router-dom";
import type { Me, Container } from "../api/types";
import type { PanelMode } from "../lib/navSection";
import { FleetPanel } from "./FleetPanel";
import { ContainerPanel } from "./ContainerPanel";
import { useTenantTasks } from "../api/queries";
import { isAdmin } from "../lib/roles";
import { Icons } from "../ui/Icon";

const navCls = ({ isActive }: { isActive: boolean }) => "fc-nav" + (isActive ? " active" : "");

function SettingsPanel({ user }: { user: Me }) {
  const admin = isAdmin(user);
  return (
    <nav className="fc-panel" aria-label="Settings navigation">
      <div className="fc-panel-head">Settings</div>
      <div className="fc-plist">
        {admin && <NavLink to="/settings/users" className={navCls}><Icons.Users /> Users</NavLink>}
        {admin && <NavLink to="/settings/api-keys" className={navCls}><Icons.Key /> API keys</NavLink>}
        {admin && <NavLink to="/settings/credentials" className={navCls}><Icons.Credentials /> Credentials</NavLink>}
      </div>
    </nav>
  );
}

function WorkflowsPanel() {
  return (
    <nav className="fc-panel" aria-label="Workflows navigation">
      <div className="fc-panel-head">Workflows</div>
      <div className="fc-plist">
        <NavLink to="/prompts" className={navCls}><Icons.Prompt /> Prompts</NavLink>
        <NavLink to="/workflows" className={navCls}><Icons.Workflow /> Workflows</NavLink>
        <NavLink to="/schedules" className={navCls}><Icons.Clock /> Scheduled runs</NavLink>
      </div>
    </nav>
  );
}

function TasksPanel() {
  const tasks = useTenantTasks().data?.tasks ?? [];
  const running = tasks.filter((t) => t.status === "running");
  return (
    <nav className="fc-panel" aria-label="Tasks navigation">
      <div className="fc-panel-head">Tasks</div>
      <div className="fc-plist">
        <NavLink end to="/tasks" className={navCls}>
          <Icons.Checklist /> <span>Activity</span>
          <span className="badge">{running.length}</span>
        </NavLink>
        {running.length > 0 && <div className="fc-glab">Running now</div>}
        {running.map((t) => (
          <NavLink key={t.task_id} to={`/containers/${t.container_id}/tasks/${t.task_id}`} className={navCls}>
            <span className="fc-cdot running" />
            <span>{t.container_name ?? t.container_id}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

function StaffPanel() {
  return (
    <nav className="fc-panel" aria-label="Staff navigation">
      <div className="fc-panel-head">Staff</div>
      <div className="fc-plist">
        <NavLink end to="/staff" className={navCls}><Icons.Sliders /> Overview</NavLink>
        <NavLink to="/staff/users" className={navCls}><Icons.Users /> Staff users</NavLink>
      </div>
    </nav>
  );
}

export function Panel({ mode, user, containers, cid }: {
  mode: PanelMode; user: Me; containers: Container[]; cid: string | null;
}) {
  if (mode === "container" && cid) return <ContainerPanel containers={containers} cid={cid} />;
  if (mode === "tasks") return <TasksPanel />;
  if (mode === "workflows") return <WorkflowsPanel />;
  if (mode === "settings") return <SettingsPanel user={user} />;
  if (mode === "staff") return <StaffPanel />;
  return <FleetPanel containers={containers} user={user} />;
}
