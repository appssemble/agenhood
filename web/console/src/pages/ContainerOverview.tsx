import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useContainer, useTasks, useFiles } from "../api/queries";
import { TaskBadge } from "../components/StatusBadge";
import { UpdateImagePicker } from "../components/UpdateImagePicker";
import { EmptyRow } from "../ui/EmptyState";
import { Button } from "../ui";
import { deriveStats } from "../lib/containerStats";
import { relativeFromNow } from "../lib/format";

export default function ContainerOverview() {
  const { cid } = useParams<{ cid: string }>();
  const container = useContainer(cid!).data;
  const tasks = useTasks(cid!).data?.tasks ?? [];
  const files = useFiles(cid!).data?.files ?? [];
  const { tokensToday } = deriveStats(tasks);
  const [editingImage, setEditingImage] = useState(false);
  const canUpdateImage =
    container != null &&
    ["running", "paused", "archived", "error"].includes(container.status);

  return (
    <div className="responsive-split" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
      {/* Left — Recent tasks */}
      <div className="card flush">
        <div className="card-head">
          <h3>Recent tasks</h3>
          <span className="id" style={{ marginLeft: 6 }}>latest 10</span>
          <span style={{ marginLeft: "auto" }} className="id">
            {tasks.length > 0 ? `${Math.min(tasks.length, 10)} of ${tasks.length}` : ""}
          </span>
        </div>
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Status</th>
              <th>Prompt</th>
              <th>Tokens</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {tasks.slice(0, 10).map((t) => (
              <tr key={t.task_id}>
                <td><TaskBadge status={t.status} /></td>
                <td>
                  <Link to={`/containers/${cid}/tasks/${t.task_id}`}>
                    <div className="clamp-2" style={{ fontWeight: 600, fontSize: 13 }} title={t.prompt}>{t.prompt}</div>
                  </Link>
                  <div className="id">{t.task_id}</div>
                </td>
                <td className="num">{(t.tokens_in + t.tokens_out).toLocaleString()}</td>
                <td style={{ whiteSpace: "nowrap" }}><span className="id">{relativeFromNow(t.started_at, Date.now())}</span></td>
              </tr>
            ))}
            {tasks.length === 0 && (
              <EmptyRow
                colSpan={4}
                icon="Tasks"
                title="No tasks yet"
                description="Submit a task and it will show up here."
                actions={
                  <Link to={`/containers/${cid}/submit`} className="btn btn-secondary btn-sm">
                    Submit a task
                  </Link>
                }
              />
            )}
          </tbody>
        </table>
        </div>
      </div>

      {/* Right — stat cards */}
      <div className="flex-col" style={{ gap: 12 }}>
        {/* Workspace */}
        <div className="card">
          <h3 style={{ margin: "0 0 12px", fontSize: 13.5 }}>Workspace</h3>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div>
              <div className="num" style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em" }}>
                {files.length}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--muted)" }}>files</div>
            </div>
            <Link to={`/containers/${cid}/files`} className="btn btn-ghost btn-sm">
              Open files →
            </Link>
          </div>
        </div>

        {/* Today's usage */}
        <div className="card">
          <h3 style={{ margin: "0 0 12px", fontSize: 13.5 }}>Today's usage</h3>
          <div>
            <div className="num" style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em" }}>
              {tokensToday.toLocaleString()}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>tokens today</div>
          </div>
        </div>

        {/* Image */}
        <div className="card">
          <h3 style={{ margin: "0 0 12px", fontSize: 13.5 }}>Image</h3>
          {container && (
            <>
              <div
                className="mono"
                style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em", wordBreak: "break-all" }}
              >
                {container.image_tag}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 2 }}>
                image tag · <span className="tag">{container.image_variant}</span>
              </div>
              {canUpdateImage && !editingImage && (
                <Button
                  variant="secondary"
                  size="sm"
                  style={{ marginTop: 12 }}
                  onClick={() => setEditingImage(true)}
                >
                  Update image
                </Button>
              )}
              {canUpdateImage && editingImage && (
                <UpdateImagePicker
                  cid={container.id}
                  currentTag={container.image_tag}
                  onDone={() => setEditingImage(false)}
                />
              )}
            </>
          )}
        </div>

        {/* Current config */}
        <div className="card">
          <h3 style={{ margin: "0 0 12px", fontSize: 13.5 }}>Current config</h3>
          {container && (
            <dl className="kv" style={{ gridTemplateColumns: "90px 1fr", fontSize: 12.5 }}>
              <dt>Driver</dt><dd className="mono">{container.config.driver}</dd>
              <dt>Model</dt><dd className="mono">{container.config.model}</dd>
              <dt>Tools</dt><dd>{container.config.tools.length} enabled</dd>
            </dl>
          )}
          <Link
            to={`/containers/${cid}/config`}
            style={{ fontSize: 12, color: "var(--ink)", marginTop: 8, display: "inline-block" }}
          >
            Edit configuration →
          </Link>
        </div>
      </div>
    </div>
  );
}
