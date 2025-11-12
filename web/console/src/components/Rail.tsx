// web/console/src/components/Rail.tsx
import { Link } from "react-router-dom";
import type { Me } from "../api/types";
import { Icons } from "../ui/Icon";
import { Avatar } from "../ui/Avatar";
import { Logo } from "../ui/Logo";
import type { RailSection } from "../lib/navSection";
import { API_BASE } from "../api/base";

export function Rail({ user, section }: {
  user: Me; section: RailSection;
}) {
  const cls = (s: RailSection) => "fc-rail-btn" + (section === s ? " active" : "");
  return (
    <aside className="fc-rail">
      <div className="glyph"><Logo size={16} /></div>
      <Link to="/" title="Dashboard: fleet overview" className={cls("dashboard")}>
        <Icons.Dashboard w={21} t="translate(1.333 1.333) scale(0.8889)" style={{ strokeWidth: 2.25 }} /><span className="lab">Dashboard</span>
      </Link>
      <Link to="/containers" title="Fleet: containers" className={cls("fleet")}>
        <Icons.Server w={21} /><span className="lab">Fleet</span>
      </Link>
      <Link to="/workflows" title="Workflows: prompts, automations & schedules" className={cls("workflows")}>
        <Icons.Workflow w={21} /><span className="lab">Workflows</span>
      </Link>
      <Link to="/tasks" title="Tasks: live across the fleet" className={cls("tasks")}>
        <Icons.Checklist w={21} t="translate(0.188 -0.295) scale(1.0738)" style={{ strokeWidth: 1.862 }} /><span className="lab">Tasks</span>
      </Link>
      <Link to="/settings/users" title="Settings" className={cls("settings")}>
        <Icons.Settings w={21} t="translate(2.454 2.454) scale(0.7955)" style={{ strokeWidth: 2.514 }} /><span className="lab">Settings</span>
      </Link>
      {user?.is_staff && (
        <Link to="/staff" title="Staff: cross-tenant scope" className={cls("staff")}>
          <Icons.Users w={21} t="translate(0.706 0.235) scale(0.9412)" style={{ strokeWidth: 2.125 }} /><span className="lab">Staff</span>
        </Link>
      )}
      <div className="fc-rail-spacer" />
      <a
        href={`${API_BASE}/v1/docs`}
        target="_blank"
        rel="noreferrer"
        title="API docs: Swagger UI"
        className="fc-rail-btn"
      >
        <Icons.Code w={21} /><span className="lab">API docs</span>
      </a>
      <Link to="/profile" title="Profile" aria-label="Profile" className={cls("profile")}>
        <Avatar name={user.name} size={34} />
      </Link>
    </aside>
  );
}
