import type { ContainerStatus, TaskStatus } from "../api/types";

const TRANSIENT: ContainerStatus[] = ["provisioning", "resuming", "pausing", "archiving", "recovering", "destroying", "deleting"];
const LABELS: Partial<Record<ContainerStatus, string>> = { archived: "Destroyed" };

export function ContainerBadge({ status }: { status: ContainerStatus }) {
  const busy = TRANSIENT.includes(status);

  let pillClass: string;
  if (status === "running") {
    pillClass = "pill pill-running";
  } else if (busy) {
    pillClass = "pill pill-trans";
  } else if (status === "error") {
    pillClass = "pill pill-error";
  } else {
    pillClass = "pill pill-dormant";
  }

  return (
    <span data-busy={busy} aria-busy={busy} className={pillClass}>
      {busy
        ? <span className="spin" />
        : <span className="dot" />
      }
      {LABELS[status] ?? status}
    </span>
  );
}

export function TaskBadge({ status }: { status: TaskStatus }) {
  let pillClass: string;
  let indicator: React.ReactNode;

  switch (status) {
    case "pending":
      pillClass = "pill pill-running";
      indicator = <span className="dot" />;
      break;
    case "running":
      pillClass = "pill pill-running";
      indicator = <span className="spin" />;
      break;
    case "completed":
      pillClass = "pill pill-completed";
      indicator = <span className="dot" />;
      break;
    case "failed":
    case "timed_out":
      pillClass = "pill pill-warn";
      indicator = <span className="dot" />;
      break;
    case "cancelled":
      pillClass = "pill pill-cancelled";
      indicator = <span className="dot" />;
      break;
    default:
      pillClass = "pill pill-dormant";
      indicator = <span className="dot" />;
  }

  return (
    <span className={pillClass}>
      {indicator}
      {status}
    </span>
  );
}
