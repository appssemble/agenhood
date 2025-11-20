import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useContainers, useLifecycle } from "../api/queries";
import { useAuth } from "../auth/useAuth";
import { ContainerBadge } from "../components/StatusBadge";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ConfirmBar } from "../components/ConfirmBar";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import { Button, SegControl } from "../ui";
import { EmptyRow } from "../ui/EmptyState";
import { Icons } from "../ui/Icon";
import { usePins } from "../lib/pins";
import { isAdmin } from "../lib/roles";
import type { Container } from "../api/types";

type Filter = "all" | "running" | "paused" | "archived" | "error";

const FILTER_OPTIONS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "archived", label: "Destroyed" },
  { value: "error", label: "Errored" },
];

function Row({ c, isAdmin }: { c: Container; isAdmin: boolean }) {
  const lc = useLifecycle(c.id);
  const toast = useToast();
  const navigate = useNavigate();
  const [forcePause, setForcePause] = useState(false);
  const [destroyOpen, setDestroyOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const { isPinned, toggle } = usePins();

  async function pause(force: boolean) {
    try {
      await lc.pause.mutateAsync(force);
      setForcePause(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) { setForcePause(true); }
      else { toast.error("Couldn't pause container", err instanceof ApiError ? err.message : undefined); }
    }
  }

  const pinned = isPinned(c.id);

  return (
    <>
      <tr
        onClick={(e) => {
          // Row opens the container, except clicks on inline controls (pin,
          // lifecycle buttons).
          if ((e.target as HTMLElement).closest("button, a")) return;
          navigate(`/containers/${c.id}`);
        }}
        style={{ cursor: "pointer" }}
      >
        <td>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              onClick={() => toggle(c.id)}
              title={pinned ? "Unpin" : "Pin"}
              aria-label={pinned ? "Unpin container" : "Pin container"}
              style={{ color: pinned ? "var(--ink)" : "var(--muted)", background: "none", border: "none", cursor: "pointer", padding: 2 }}
            >
              <Icons.Container style={{ width: 18, height: 18 }} />
            </button>
            <div>
              <div style={{ fontWeight: 600 }}>{c.name}</div>
              <div className="id">{c.id}</div>
            </div>
          </div>
        </td>
        <td><ContainerBadge status={c.status} /></td>
        <td>
          <div>{c.config.driver}</div>
          <div className="id">{c.config.model}</div>
        </td>
        <td><span className="tag">{c.image_variant}</span></td>
        <td className="num">—</td>
        <td><span className="id">{c.last_task_at ? c.last_task_at : "—"}</span></td>
        <td style={{ textAlign: "right" }}>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            {c.status === "error" && isAdmin && (
              <Button size="sm" variant="primary" onClick={() => lc.recover.mutate()}>Recover</Button>
            )}
            {c.status === "running" && (
              <Button size="sm" variant="secondary" onClick={() => pause(false)}>Pause</Button>
            )}
            {c.status === "paused" && (
              <Button size="sm" variant="secondary" onClick={() => lc.resume.mutate()}>Resume</Button>
            )}
            {c.status === "archived" && (
              <Button size="sm" variant="secondary" onClick={async () => {
                try { await lc.restore.mutateAsync(); }
                catch (err) { toast.error("Couldn't restore container", err instanceof ApiError ? err.message : undefined); }
              }}>Restore</Button>
            )}
            {isAdmin && (c.status === "running" || c.status === "paused") && (
              <Button size="sm" variant="danger" onClick={() => setDestroyOpen(true)}>Destroy</Button>
            )}
            {/* Permanent delete is available to admins from any settled state
                (e.g. running, paused, archived, error) — not while a delete is
                already in flight. */}
            {isAdmin && c.status !== "deleting" && (
              <Button size="sm" variant="danger" onClick={() => setDeleteOpen(true)}>Delete</Button>
            )}
          </div>
        </td>
      </tr>
      {forcePause && (
        <tr>
          <td colSpan={7} className="px-3 pb-3">
            <ConfirmBar
              message={`Couldn't pause ${c.name}. It has running tasks. Force pause cancels them first.`}
              confirmLabel="Force pause" cancelLabel="Keep running"
              onConfirm={() => pause(true)} onCancel={() => setForcePause(false)} />
          </td>
        </tr>
      )}
      <ConfirmDialog
        open={destroyOpen} title="Destroy container"
        body="Removes the running container but keeps the data so it can be restored later."
        confirmLabel="Destroy"
        onConfirm={async () => {
          setDestroyOpen(false);
          try { await lc.destroy.mutateAsync(); }
          catch (err) { toast.error("Couldn't destroy container", err instanceof ApiError ? err.message : undefined); }
        }}
        onCancel={() => setDestroyOpen(false)} />
      <ConfirmDialog
        open={deleteOpen} title="Delete container"
        body="Permanently deletes the container and all of its data. This cannot be undone."
        confirmLabel="Delete forever"
        onConfirm={async () => {
          setDeleteOpen(false);
          try { await lc.delete.mutateAsync(); }
          catch (err) { toast.error("Couldn't delete container", err instanceof ApiError ? err.message : undefined); }
        }}
        onCancel={() => setDeleteOpen(false)} />
    </>
  );
}

export default function Containers() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const { data, isLoading } = useContainers();
  const containers = data?.containers ?? [];
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const s = q.trim().toLowerCase();
  const filtered = containers.filter((c) => {
    const statusOk = filter === "all" || c.status === filter;
    const searchOk =
      !s ||
      c.name.toLowerCase().includes(s) ||
      c.id.toLowerCase().includes(s) ||
      (c.external_id ?? "").toLowerCase().includes(s);
    return statusOk && searchOk;
  });
  const runningCount = containers.filter((c) => c.status === "running").length;

  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;

  return (
    <div className="page">
      {/* Page header */}
      <div className="page-title" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>Containers</h1>
        <span className="pill pill-dormant" style={{ fontWeight: 500 }}>
          {containers.length} total · {runningCount} running
        </span>
      </div>

      {/* Toolbar: search (left) + status filter + New (right) */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="search-pill fluid-w" style={{ width: 360, maxWidth: "100%" }}>
          <Icons.Search />
          <input
            placeholder="Search containers…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <SegControl
            options={FILTER_OPTIONS}
            value={filter}
            onChange={setFilter}
          />
          <Link
            to="/containers/new"
            className="btn btn-primary btn-sm"
            style={{ gap: 6, padding: "6px 12px 6px 10px" }}
          >
            <Icons.Plus /> New
          </Link>
        </div>
      </div>

      {/* Fleet table */}
      <div className="card flush">
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>External id</th>
              <th>Status</th>
              <th>Driver / model</th>
              <th>Variant</th>
              <th>Tasks</th>
              <th>Last activity</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <Row key={c.id} c={c} isAdmin={admin} />
            ))}
            {filtered.length === 0 && (
              <EmptyRow
                colSpan={7}
                icon="Container"
                title={containers.length === 0 ? "No containers yet" : "No matching containers"}
                description={
                  containers.length === 0
                    ? "Spin up a container to give your agents a place to run tasks."
                    : "No containers match your search or status filter. Try clearing them."
                }
                actions={
                  containers.length === 0 ? (
                    <Link to="/containers/new" className="btn btn-primary btn-sm" style={{ gap: 6, padding: "6px 12px 6px 10px" }}>
                      <Icons.Plus /> New container
                    </Link>
                  ) : undefined
                }
              />
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
