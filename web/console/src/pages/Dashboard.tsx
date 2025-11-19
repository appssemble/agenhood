import { Link } from "react-router-dom";
import { useContainers, useTemplates } from "../api/queries";
import { Icons } from "../ui/Icon";
import type { Template } from "../api/types";
import DashboardAnalytics from "./DashboardAnalytics";

function TemplateCard({ template, index }: { template: Template; index: number }) {
  const isPrimary = template.is_builtin && index === 0;
  const toolSummary = template.tools.length > 0 ? `tools: ${template.tools.slice(0, 3).join(" · ")}` : null;
  const tags: string[] = [];
  if (template.model) tags.push(template.model);
  if (toolSummary) tags.push(toolSummary);
  if (template.system_prompt_mode) tags.push(`${template.system_prompt_mode} mode`);

  return (
    <div
      className="card"
      style={{
        padding: 0,
        overflow: "hidden",
        borderColor: isPrimary ? "var(--ink)" : "var(--border)",
        textAlign: "left",
      }}
    >
      <div style={{ padding: 16, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 38,
            height: 38,
            borderRadius: 10,
            background: isPrimary ? "var(--p-300)" : "var(--surface-3)",
            display: "grid",
            placeItems: "center",
          }}
        >
          {isPrimary ? <Icons.Star sw={2} w={18} /> : <Icons.Terminal w={18} />}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em" }}>{template.name}</div>
          <div style={{ fontSize: 11.5, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>driver: {template.driver}</div>
        </div>
        {isPrimary && (
          <span className="pill pill-running" style={{ fontSize: 11 }}>recommended</span>
        )}
      </div>
      <div style={{ padding: 16 }}>
        <div style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.55, marginBottom: 10 }}>
          {template.is_builtin ? "Built-in template" : "Tenant template"}
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 14 }}>
          {tags.map((t) => (
            <span key={t} className="tag" style={{ fontSize: 10.5 }}>{t}</span>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Link
            to="/containers/new"
            className={"btn btn-sm " + (isPrimary ? "btn-primary" : "btn-secondary")}
          >
            <Icons.Plus /> Create container from this template
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: containersData, isLoading } = useContainers();
  const { data: templatesData } = useTemplates();
  const containers = containersData?.containers ?? [];
  const templates = templatesData?.templates ?? [];

  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;

  if (containers.length === 0) {
    return (
      <div
        className="page"
        style={{ padding: 32, alignItems: "center", justifyContent: "center", display: "flex", flexDirection: "column", gap: 16 }}
      >
        {/* Hero copy */}
        <div className="fluid-w" style={{ maxWidth: 760, width: "100%", textAlign: "center", padding: "32px 24px 8px" }}>
          <div
            style={{
              display: "inline-flex",
              gap: 8,
              alignItems: "center",
              padding: "6px 12px",
              borderRadius: 999,
              background: "var(--ink)",
              color: "var(--p-300)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: ".06em",
              marginBottom: 16,
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--p-400)", display: "inline-block" }}></span>
            WELCOME
          </div>
          <h1 style={{ fontSize: 38, lineHeight: 1.1, letterSpacing: "-0.03em", margin: "0 0 10px", fontWeight: 800 }}>
            Start with{" "}
            <span style={{ background: "var(--p-300)", padding: "0 10px", borderRadius: 8 }}>one agent</span>
            . Add more as you need them.
          </h1>
          <p style={{ fontSize: 15, color: "var(--ink-2)", maxWidth: 580, margin: "0 auto 12px", lineHeight: 1.5 }}>
            Each container is a long-lived sandbox with its own file workspace and one agent configuration.
            Most teams run one container per end-user, per workflow, or per environment.
          </p>
          <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 24px" }}>
            Pick a template to bootstrap, or start from scratch. You can change everything later.
          </p>
        </div>

        {/* Template cards or CTA */}
        {templates.length > 0 ? (
          <div className="responsive-split" style={{ maxWidth: 880, width: "100%", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            {templates.map((t: Template, i: number) => (
              <TemplateCard key={t.id} template={t} index={i} />
            ))}
          </div>
        ) : (
          <Link to="/containers" className="btn btn-primary btn-sm">
            Create your first container
          </Link>
        )}

        {/* Start from scratch */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>or</span>
          <Link to="/containers/new" className="btn btn-secondary">
            <Icons.Plus /> Start from scratch
          </Link>
        </div>
      </div>
    );
  }

  return <DashboardAnalytics />;
}
