import { useState } from "react";
import { Link } from "react-router-dom";
import { Icons } from "../ui/Icon";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { useToast } from "./Toast";
import { useRunWorkflow } from "../api/queries";
import { ApiError } from "../api/client";
import { relativeFromNow } from "../lib/format";
import type { Workflow } from "../api/types";

const MAX_ROWS = 4;
const MAX_DOTS = 6;

function StepDots({ count }: { count: number }) {
  const dots = Math.min(count, MAX_DOTS);
  return (
    <span className="step-dots" aria-hidden>
      {Array.from({ length: dots }, (_, i) => <i key={i} />)}
      {count > MAX_DOTS && <span className="more">+{count - MAX_DOTS}</span>}
    </span>
  );
}

export function WorkflowsPanel({ workflows }: { workflows: Workflow[] }) {
  const toast = useToast();
  const run = useRunWorkflow();
  const [runningId, setRunningId] = useState<string | null>(null);

  const total = workflows.length;
  const rows = [...workflows]
    .sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1))
    .slice(0, MAX_ROWS);

  async function onRun(wf: Workflow) {
    setRunningId(wf.id);
    try {
      await run.mutateAsync(wf.id);
      toast.success(`Started ${wf.name}`);
    } catch (err) {
      toast.error("Couldn't start workflow", err instanceof ApiError ? err.message : undefined);
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div>
      <div className="panel-head">
        <span className="panel-title">Workflows</span>
        {total > 0 && <span className="count-chip">{total}</span>}
        <Link to="/workflows" className="panel-link">
          {total > 0 ? "View all" : "Open"} <Icons.ArrowRight w={13} />
        </Link>
      </div>

      {total === 0 ? (
        <EmptyState
          size="sm"
          icon="Workflow"
          title="No workflows yet"
          description="Chain prompts into a repeatable, multi-step run."
          actions={<Link to="/workflows/new" className="btn btn-primary btn-sm"><Icons.Plus w={14} /> New workflow</Link>}
        />
      ) : (
        <div>
          {rows.map((wf) => {
            const steps = wf.steps.length;
            const containers = new Set(wf.steps.map((s) => s.container_id)).size;
            const busy = runningId === wf.id;
            return (
              <div key={wf.id} className="dash-row">
                <div className="dash-ico"><Icons.Workflow w={15} /></div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Link to={`/workflows/${wf.id}/edit`} className="row-name" style={{ display: "block" }} title={wf.name}>
                    {wf.name}
                  </Link>
                  <div className="row-meta">
                    <StepDots count={steps} />
                    <span>{steps} step{steps === 1 ? "" : "s"} · {containers} container{containers === 1 ? "" : "s"}</span>
                    <span style={{ color: "var(--muted-2)" }}>· {relativeFromNow(wf.updated_at, Date.now())}</span>
                  </div>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy || steps === 0}
                  aria-label={`Run ${wf.name}`}
                  onClick={() => onRun(wf)}
                  style={{ flexShrink: 0, gap: 5, minWidth: 70, justifyContent: "center" }}
                >
                  {busy ? "Running…" : <><Icons.Play w={13} /> Run</>}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
