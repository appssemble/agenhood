import { Outlet, useParams, useNavigate, useLocation } from "react-router-dom";
import { useContainer, useTasks, useLifecycle } from "../api/queries";
import { deriveStats } from "../lib/containerStats";
import { SummaryStrip } from "../components/SummaryStrip";
import { Button } from "../ui";

export default function ContainerLayout() {
  const { cid } = useParams<{ cid: string }>();
  const { data: container } = useContainer(cid!);
  const { running, tokensToday } = deriveStats(useTasks(cid!).data?.tasks ?? []);
  const lifecycle = useLifecycle(cid!);
  const navigate = useNavigate();
  const location = useLocation();

  if (!container) return <div className="p-8 text-sm text-muted">Loading…</div>;

  // When viewing a task detail, render only the outlet (the task viewer owns its own full-screen header)
  const isTaskRoute = location.pathname.includes("/tasks/");
  if (isTaskRoute) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
        <Outlet />
      </div>
    );
  }

  const actions = (
    <>
      <Button variant="primary" size="sm" onClick={() => navigate(`/containers/${cid}/submit`)}>
        New task
      </Button>
      {container.status === "running" && (
        <Button variant="secondary" size="sm" onClick={() => lifecycle.pause.mutate(false)}>
          Pause
        </Button>
      )}
      {container.status === "paused" && (
        <Button variant="secondary" size="sm" onClick={() => lifecycle.resume.mutate()}>
          Wake up
        </Button>
      )}
    </>
  );

  // Submit task owns a height-bounded shell so its chat layout can fill the
  // available space (scrolling thread + pinned composer), while still keeping
  // the summary strip on top.
  const isSubmitRoute = location.pathname.endsWith("/submit");
  if (isSubmitRoute) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", padding: 22, gap: 16 }}>
        <div style={{ flexShrink: 0 }}>
          <SummaryStrip container={container} running={running} tokensToday={tokensToday} actions={actions} />
        </div>
        <Outlet />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-[22px]">
      <SummaryStrip container={container} running={running} tokensToday={tokensToday} actions={actions} />
      <Outlet />
    </div>
  );
}
