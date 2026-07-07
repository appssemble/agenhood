import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTemplates, useCreateContainer } from "../api/queries";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import { Button, SegControl, Field, Input, Note } from "../ui";
import { Icons } from "../ui/Icon";
import { ModelPicker } from "../components/ModelPicker";
import type { Template } from "../api/types";

function templateTags(t: Template): string[] {
  const tags: string[] = [];
  if (t.model) tags.push(t.model);
  const toolCount = t.tools?.length ?? 0;
  const skillCount = t.skills?.length ?? 0;
  if (toolCount) tags.push(`${toolCount} tool${toolCount === 1 ? "" : "s"}`);
  if (skillCount) tags.push(`${skillCount} skill${skillCount === 1 ? "" : "s"}`);
  if (t.system_prompt_mode) tags.push(`${t.system_prompt_mode} mode`);
  return tags;
}

function TemplateCard({
  template,
  selected,
  onSelect,
}: {
  template: Template;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`nc-tpl ${selected ? "sel" : ""}`}
    >
      {selected && (
        <span className="nc-tpl-check" aria-hidden="true">
          <Icons.Check />
        </span>
      )}
      <div className="nc-tpl-top">
        <span className="nc-tpl-ico">
          <Icons.Terminal w={18} />
        </span>
        <span className="nc-tpl-titles">
          <span className="nc-tpl-name">{template.name}</span>
          <span className="nc-tpl-driver">{template.driver}</span>
        </span>
      </div>
      <div className="nc-tpl-tags">
        <span className="tag" style={{ fontSize: 10.5 }}>
          {template.is_builtin ? "Built-in" : "Tenant"}
        </span>
        {templateTags(template).map((t) => (
          <span key={t} className="tag" style={{ fontSize: 10.5 }}>{t}</span>
        ))}
      </div>
    </button>
  );
}

function ReviewRow({ label, value, mono }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <div className="nc-rev">
      <span className="k">{label}</span>
      <span className={`v ${mono ? "mono" : ""} ${value ? "" : "empty"}`.trim()}>
        {value || "Not set"}
      </span>
    </div>
  );
}

export default function CreateContainer() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data } = useTemplates();
  const create = useCreateContainer();
  const templates = data?.templates ?? [];
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [variant, setVariant] = useState<"full" | "slim">("full");
  const [model, setModel] = useState("");
  const [memLimit, setMemLimit] = useState("");
  const [cpus, setCpus] = useState("");

  const chosen = templates.find((t) => t.id === templateId) ?? templates[0];
  const effectiveTemplateId = templateId ?? chosen?.id ?? "";

  // Default model when the chosen template changes
  useEffect(() => {
    if (chosen?.model) setModel(chosen.model);
    else setModel("");
  }, [chosen?.id]);

  const missing: string[] = [];
  if (!chosen) missing.push("Select a template");
  if (!name.trim()) missing.push("Name the container");
  if (!model) missing.push("Choose a model");
  const ready = missing.length === 0;

  async function onCreate() {
    try {
      const config = chosen
        ? {
            driver: chosen.driver,
            model,
            system_prompt: chosen.system_prompt,
            system_prompt_mode: chosen.system_prompt_mode,
            tools: chosen.tools,
            context: chosen.context,
          }
        : undefined;
      const trimmedMem = memLimit.trim();
      const parsedCpus = cpus.trim() ? Number(cpus.trim()) : undefined;
      const resource_limits =
        trimmedMem || parsedCpus !== undefined
          ? { ...(trimmedMem && { mem_limit: trimmedMem }), ...(parsedCpus !== undefined && { cpus: parsedCpus }) }
          : undefined;
      const ctr = await create.mutateAsync({
        name, template_id: effectiveTemplateId, image_variant: variant, config,
        ...(resource_limits && { resource_limits }),
      });
      navigate(`/containers/${ctr.id}`, { replace: true });
    } catch (err) {
      toast.error("Couldn't create container", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title nc-head">
        <Link to="/containers" className="nc-back">
          <Icons.ArrowLeft /> Containers
        </Link>
        <h1 className="nc-title">New container</h1>
        <p className="nc-sub">
          Pick a template, give it a name, and choose a model. Review the summary, then launch.
        </p>
      </div>

      <div className="nc-layout">
        {/* Config column */}
        <div className="nc-main">
          {/* Step 1 — template */}
          <section className="section-card">
            <div className="section-card-head">
              <span className="nc-step">1</span>
              <div className="section-card-titles">
                <span className="section-card-title">Template</span>
                <span className="section-card-hint">Starting point for tools, prompt, and driver.</span>
              </div>
            </div>
            <div className="section-card-body">
              {templates.length === 0 ? (
                <Note>
                  No templates available yet. Create one under <b>Templates</b> first, then come back to launch a container.
                </Note>
              ) : (
                <div className="nc-tpl-grid">
                  {templates.map((t: Template) => (
                    <TemplateCard
                      key={t.id}
                      template={t}
                      selected={effectiveTemplateId === t.id}
                      onSelect={() => setTemplateId(t.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Step 2 — details */}
          <section className="section-card">
            <div className="section-card-head">
              <span className="nc-step">2</span>
              <div className="section-card-titles">
                <span className="section-card-title">Details</span>
                <span className="section-card-hint">Name, model, and image size for this container.</span>
              </div>
            </div>
            <div className="section-card-body" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 18 }}>
                <div className="fluid-w" style={{ flex: "1 1 320px", maxWidth: 380 }}>
                  <Field label="Name" htmlFor="name" hint="Lowercase letters, numbers, and dashes work best.">
                    <Input
                      id="name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. research-analyst-prod"
                      autoFocus
                    />
                  </Field>
                </div>

                <div>
                  <div style={{ marginBottom: 6, fontSize: 12.5, fontWeight: 600, color: "var(--ink-2)" }}>
                    Image variant
                  </div>
                  <SegControl
                    options={[
                      { value: "full" as const, label: "Full" },
                      { value: "slim" as const, label: "Slim" },
                    ]}
                    value={variant}
                    onChange={setVariant}
                  />
                  <div className="hint" style={{ marginTop: 6, fontSize: 11.5, color: "var(--muted)", maxWidth: 220 }}>
                    {variant === "full"
                      ? "Full image, every bundled tool preinstalled."
                      : "Slim image, smaller and faster cold starts."}
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
                <div className="fluid-w" style={{ flex: "1 1 160px", maxWidth: 200 }}>
                  <Field label="Memory (optional)" htmlFor="mem-limit" hint="e.g. 2g. Defaults by image variant.">
                    <Input
                      id="mem-limit"
                      value={memLimit}
                      onChange={(e) => setMemLimit(e.target.value)}
                      placeholder={variant === "full" ? "4g" : "2g"}
                    />
                  </Field>
                </div>
                <div className="fluid-w" style={{ flex: "1 1 160px", maxWidth: 200 }}>
                  <Field label="CPUs (optional)" htmlFor="cpus" hint="e.g. 1.5. Defaults by image variant.">
                    <Input
                      id="cpus"
                      value={cpus}
                      onChange={(e) => setCpus(e.target.value)}
                      placeholder={variant === "full" ? "2" : "1"}
                    />
                  </Field>
                </div>
              </div>

              <div className="fluid-w" style={{ maxWidth: 480 }}>
                <Field label="Model">
                  <ModelPicker driver={chosen?.driver ?? ""} value={model} onChange={setModel} />
                </Field>
              </div>
            </div>
          </section>
        </div>

        {/* Review aside */}
        <aside className="nc-summary">
          <div className="nc-rev-card">
            <div className="nc-rev-head">
              <Icons.Checklist />
              <span className="t">Review</span>
            </div>
            <div className="nc-rev-body">
              <ReviewRow label="Template" value={chosen?.name ?? null} />
              <ReviewRow label="Name" value={name.trim() || null} mono />
              <ReviewRow label="Model" value={model || null} mono />
              <ReviewRow label="Driver" value={chosen?.driver ?? null} mono />
              <ReviewRow label="Image" value={variant === "full" ? "Full" : "Slim"} />
              <ReviewRow label="Memory" value={memLimit.trim() || null} mono />
              <ReviewRow label="CPUs" value={cpus.trim() || null} mono />
            </div>
            <div className="nc-rev-foot">
              <Button
                variant="primary"
                size="md"
                onClick={onCreate}
                disabled={!ready || create.isPending}
              >
                {create.isPending ? (
                  <><span className="cw-spin" aria-hidden="true" /> Creating…</>
                ) : (
                  "Create container"
                )}
              </Button>
              {!ready && (
                <div className="nc-missing">
                  <Icons.Info />
                  <span>{missing[0]} to continue.</span>
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
