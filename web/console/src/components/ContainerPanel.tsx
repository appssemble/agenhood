import { NavLink } from "react-router-dom";
import type { Container } from "../api/types";
import { ContainerSwitcher } from "./ContainerSwitcher";
import { Icons } from "../ui/Icon";

const navCls = ({ isActive }: { isActive: boolean }) => "fc-nav" + (isActive ? " active" : "");

export function ContainerPanel({ containers, cid }: { containers: Container[]; cid: string }) {
  return (
    <nav className="fc-panel" aria-label="Container navigation">
      <div className="fc-panel-head">Container</div>
      <ContainerSwitcher containers={containers} activeId={cid} />
      <div className="fc-plist">
        <NavLink end to={`/containers/${cid}`} className={navCls}><Icons.Sliders /> Overview</NavLink>
        <NavLink to={`/containers/${cid}/config`} className={navCls}><Icons.Settings /> Configuration</NavLink>
        <NavLink to={`/containers/${cid}/files`} className={navCls}><Icons.Folder /> Files</NavLink>
        <NavLink to={`/containers/${cid}/snapshots`} className={navCls}><Icons.Refresh /> Snapshots</NavLink>
        <NavLink to={`/containers/${cid}/submit`} className={navCls}><Icons.Send /> Submit Task</NavLink>
        <NavLink to={`/containers/${cid}/console`} className={navCls}><Icons.Terminal /> Console</NavLink>
        <NavLink to={`/containers/${cid}/history`} className={navCls}><Icons.History /> History</NavLink>
      </div>
    </nav>
  );
}
