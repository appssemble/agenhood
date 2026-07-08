import type { AgentConfig, ContextSpec, ToolSpec } from "../api/types";

// Mirrors spec §3.7 prompt assembly. augment = scaffolding + user prompt;
// replace = exactly config.system_prompt (verbatim, nothing injected).
export function assemblePrompt(config: AgentConfig, toolSpecs: ToolSpec[]): string {
  if (config.system_prompt_mode === "replace") {
    return config.system_prompt;
  }

  const tools = config.tools
    .map((name) => toolSpecs.find((t) => t.name === name))
    .filter((t): t is ToolSpec => !!t)
    .map((t) => `  • ${t.name}${t.requires_image_feature ? ` (requires \`full\` image variant)` : ""}`)
    .join("\n");

  // Templates from the API can carry a sparse context ({} for built-ins and
  // duplicates) — only container configs are pydantic-normalized upstream.
  const ctx: Partial<ContextSpec> = config.context ?? {};
  const vars = Object.entries(ctx.variables ?? {}).map(([k, v]) => `  $${k} = ${v}`).join("\n");
  const files = ctx.files?.length ? `  attached: ${ctx.files.join(", ")}` : "";
  const text = ctx.text ? `  ${ctx.text}` : "";
  const contextBlock = [vars, text, files].filter(Boolean).join("\n");

  return [
    "## SYSTEM",
    "",
    "You are an agent in the agenhood runtime.",
    "",
    "You have access to the following tools. Call them by name with valid JSON arguments:",
    "",
    tools || "  (no tools enabled)",
    "",
    "Your workspace persists at /workspace.",
    "",
    "## STANDING CONTEXT",
    "",
    contextBlock || "  (none)",
    "",
    "## INSTRUCTIONS",
    "",
    config.system_prompt,
    "",
    "## OUTPUT",
    "",
    "Use the tools above. When the task is complete, output the final result",
    "inline (text) or via write_file (files), or return JSON matching the",
    "provided schema (structured). You must call `done` to finish.",
    "",
  ].join("\n");
}
