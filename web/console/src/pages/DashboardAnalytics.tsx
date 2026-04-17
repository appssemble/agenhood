import type { ReactNode } from "react";
import { Card } from "../ui/Card";
import { RangeToggle, useRange } from "../components/RangeToggle";
import { MetricsBento } from "../components/MetricsBento";
import { TrendChart } from "../components/TrendChart";
import { TopContainers } from "../components/TopContainers";
import { ActivityFeed } from "../components/ActivityFeed";
import { WorkflowsPanel } from "../components/WorkflowsPanel";
import { PromptsPanel } from "../components/PromptsPanel";
import { Icons } from "../ui/Icon";
import {
  useContainers, useAnalyticsUsage, useAnalyticsBreakdown, useTenantTasks,
  useWorkflows, usePrompts,
} from "../api/queries";
import type { BreakdownGroup } from "../api/types";
import type { KpiTotals } from "../components/KpiRow";

const RANGE_LABEL: Record<string, string> = {
  "24h": "the last 24 hours",
  "7d": "the last 7 days",
  "30d": "the last 30 days",
};

function CardError({ what }: { what: string }) {
  return <div style={{ color: "var(--err-700)", fontSize: 13 }}>Couldn't load {what}.</div>;
}
function CardSkeleton() {
  return <div style={{ color: "var(--muted)", fontSize: 13 }}>Loading…</div>;
}

function SectionLabel({ icon, title, children }: { icon: keyof typeof Icons; title: string; children?: ReactNode }) {
  const Ico = Icons[icon] as (p: { w?: number }) => JSX.Element;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
      <span style={{ color: "var(--muted)", display: "inline-flex" }}><Ico w={15} /></span>
      <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em" }}>{title}</span>
      {children}
    </div>
  );
}

function totalsFromStatus(groups: BreakdownGroup[]): KpiTotals {
  let tokens = 0, tasks = 0, iterations = 0, completed = 0;
  for (const g of groups) {
    tokens += g.tokens_in + g.tokens_out;
    tasks += g.tasks;
    iterations += g.iterations;
    if (g.key === "completed") completed += g.tasks;
  }
  return { tokens, tasks, iterations, successRate: tasks > 0 ? completed / tasks : null };
}

export default function DashboardAnalytics() {
  const range = useRange();
  const containers = useContainers();
  const usage = useAnalyticsUsage(range);
  const status = useAnalyticsBreakdown("status", range);
  const byContainer = useAnalyticsBreakdown("container", range);
  const tasks = useTenantTasks(12);
  const workflows = useWorkflows();
  const prompts = usePrompts();

  return (
    <div className="page">
      <div className="page-title" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Dashboard</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>Your fleet over {RANGE_LABEL[range] ?? "the selected period"}.</div>
        </div>
        <RangeToggle />
      </div>

      {/* Headline metrics — bento */}
      {status.isLoading ? <Card className="lift" style={{ padding: 18 }}><CardSkeleton /></Card>
        : status.isError ? <Card className="lift" style={{ padding: 18 }}><CardError what="usage totals" /></Card>
        : (
          <MetricsBento
            totals={totalsFromStatus(status.data!.groups)}
            series={usage.data?.series ?? []}
            containers={containers.data?.containers ?? []}
          />
        )}

      {/* Usage trend */}
      <Card className="lift" style={{ padding: 18 }}>
        <SectionLabel icon="History" title="Usage trend" />
        {usage.isLoading ? <CardSkeleton />
          : usage.isError ? <CardError what="the usage trend" />
          : <TrendChart series={usage.data!.series} interval={usage.data!.interval} />}
      </Card>

      <div className="responsive-split" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14 }}>
        <Card className="lift" style={{ padding: 18 }}>
          <SectionLabel icon="Container" title="Top containers" />
          {byContainer.isLoading ? <CardSkeleton />
            : byContainer.isError ? <CardError what="top containers" />
            : <TopContainers groups={byContainer.data!.groups} />}
        </Card>
        <Card className="lift" style={{ padding: 18 }}>
          <SectionLabel icon="History" title="Recent activity" />
          {tasks.isLoading ? <CardSkeleton />
            : tasks.isError ? <CardError what="recent activity" />
            : <ActivityFeed tasks={tasks.data!.tasks} />}
        </Card>
      </div>

      <div className="responsive-split" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Card className="lift" style={{ padding: 18 }}>
          {workflows.isLoading ? <CardSkeleton />
            : workflows.isError ? <CardError what="workflows" />
            : <WorkflowsPanel workflows={workflows.data!.workflows} />}
        </Card>
        <Card className="lift" style={{ padding: 18 }}>
          {prompts.isLoading ? <CardSkeleton />
            : prompts.isError ? <CardError what="prompts" />
            : <PromptsPanel prompts={prompts.data!.prompts} />}
        </Card>
      </div>
    </div>
  );
}
