import { useMemo, useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  useWorkflow, useWorkflowRuns, useWorkflowRun, usePrompts, useContainers,
  useScheduledTasks, useRunWorkflow, useDeleteWorkflow,
} from "../../api/queries";
import { useToast } from "../../components/Toast";
import { ApiError } from "../../api/client";
import { Button } from "../../ui/Button";
import { Icons } from "../../ui/Icon";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { MetricStrip } from "./detail/MetricStrip";
import { PipelineTrack } from "./detail/PipelineTrack";
import { StepDetailPanel } from "./detail/StepDetailPanel";
import { RunsList } from "./detail/RunsList";
import { buildPipelineVMs, buildStepDetailVM, runMetrics } from "./detail/derive";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function WorkflowDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const nowMs = useNow(1000);

  const wfQ = useWorkflow(id);
  const runsQ = useWorkflowRuns(id);
  const promptsQ = usePrompts();
  const containersQ = useContainers();
  const schedulesQ = useScheduledTasks();
  const runMut = useRunWorkflow();
  const delMut = useDeleteWorkflow();

  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Default the selected run to the newest once runs arrive.
  const effectiveRunId = selectedRunId ?? runs[0]?.id ?? null;
  const detailQ = useWorkflowRun(id, effectiveRunId);

  const workflow = wfQ.data;
  const prompts = promptsQ.data?.prompts ?? [];
  const containers = containersQ.data?.containers ?? [];
  // Real useScheduledTasks response key is { scheduled_tasks: ScheduledTask[] }
  const schedules = schedulesQ.data?.scheduled_tasks ?? [];

  const schedule = useMemo(
    () => schedules.find((s) => s.target.kind === "workflow" && s.target.workflow_id === id),
    [schedules, id],
  );

  const metrics = useMemo(() => runMetrics(runs), [runs]);
  const detail = detailQ.data ?? null;

  const pipelineVMs = useMemo(
    () => (workflow ? buildPipelineVMs({ workflow, detail, prompts, containers, nowMs }) : []),
    [workflow, detail, prompts, containers, nowMs],
  );

  if (wfQ.isLoading) {
    return <div className="page"><div className="page-title">Loading…</div></div>;
  }
  if (wfQ.isError || !workflow) {
    return (
      <div className="page">
        <div className="page-title">
          <div style={{ fontSize: 16, color: "var(--muted)" }}>Couldn't load this workflow.</div>
          <Button variant="secondary" size="sm" onClick={() => navigate("/workflows")} style={{ marginTop: 10 }}>
            Back to workflows
          </Button>
        </div>
      </div>
    );
  }

  const containerCount = new Set(workflow.steps.map((s) => s.container_id)).size;

  async function onRunNow() {
    await runMut.mutateAsync(id);
    setSelectedRunId(null); // re-default to newest on next poll
    setSelectedStep(null);
  }
  async function onDelete() {
    try {
      await delMut.mutateAsync(id);
      navigate("/workflows");
    } catch (err) {
      toast.error("Couldn't delete workflow", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="page">
      {/* Header — dark summary strip (matches the container detail top card).
          The "Workflows / {name}" breadcrumb is shown by the shell ContextBar,
          like every other page — no separate in-page breadcrumb here. */}
      <MetricStrip
        name={workflow.name}
        workflowId={workflow.id}
        scheduled={!!schedule}
        stepCount={workflow.steps.length}
        lastRun={runs[0]}
        metrics={metrics}
        containerCount={containerCount}
        nowMs={nowMs}
        actions={
          <>
            <Button variant="primary" size="sm" disabled={runMut.isPending} onClick={onRunNow}>
              <Icons.Play w={14} /> Run now
            </Button>
            <Button variant="secondary" size="sm" onClick={() => navigate(`/workflows/${id}/edit`)}>Edit</Button>
            <Button variant="secondary" size="sm" onClick={() => navigate(`/schedules/new?kind=workflow&workflow_id=${id}`)}>Schedule</Button>
            <Button variant="danger" size="sm" aria-label="Delete workflow" onClick={() => setConfirmDelete(true)}>
              <Icons.Trash w={14} />
            </Button>
          </>
        }
      />

      {workflow.description && (
        <p className="clamp-2" style={{ fontSize: 13, color: "var(--muted)", margin: 0, paddingLeft: 4, maxWidth: 620 }}>
          {workflow.description}
        </p>
      )}

      {/* Pipeline + step detail */}
      <div className="card flush">
        <div className="card-head">
          <h3>Pipeline</h3>
          <span className="spacer" />
          <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
            {effectiveRunId ? `Showing run ${effectiveRunId}` : "Definition"}
          </span>
        </div>
        <PipelineTrack
          steps={pipelineVMs}
          selectedIndex={selectedStep}
          onSelect={(i) => setSelectedStep((cur) => (cur === i ? null : i))}
        />
        {selectedStep !== null && (
          <StepDetailPanel
            vm={buildStepDetailVM({ workflow, detail, prompts, containers, index: selectedStep, nowMs })}
          />
        )}
      </div>

      <RunsList
        runs={runs}
        selectedRunId={effectiveRunId}
        onSelect={(rid) => { setSelectedRunId(rid); setSelectedStep(null); }}
        nowMs={nowMs}
        onRunNow={onRunNow}
        running={runMut.isPending}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="Delete workflow?"
        body={`"${workflow.name}" and its run history will be removed. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => { setConfirmDelete(false); void onDelete(); }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
