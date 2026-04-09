import { describe, it, expect } from "vitest";
import { assemblePrompt } from "./assemblePrompt";
import type { AgentConfig, ToolSpec } from "../api/types";

const toolSpecs: ToolSpec[] = [
  { name: "read_file", description: "Read a file", input_schema: {}, requires_image_feature: null },
  { name: "web_fetch", description: "Fetch a URL", input_schema: {}, requires_image_feature: "chromium" },
];

function cfg(over: Partial<AgentConfig> = {}): AgentConfig {
  return { driver: "vanilla", model: "m", system_prompt: "You are a research analyst.",
    system_prompt_mode: "augment", tools: ["read_file", "web_fetch"],
    context: { variables: { company: "Acme" }, text: "Be terse.", files: ["style.md"] }, ...over };
}

describe("assemblePrompt", () => {
  it("augment mode wraps the user prompt and lists enabled tools + context", () => {
    const out = assemblePrompt(cfg(), toolSpecs);
    expect(out).toContain("## SYSTEM");
    expect(out).toContain("read_file");
    expect(out).toContain("web_fetch");
    expect(out).toContain("You are a research analyst.");          // user text present
    expect(out).toContain("Acme");                                  // context variable
    expect(out).toContain("style.md");                             // context file
    expect(out).toContain("## OUTPUT");
  });

  it("replace mode returns the system prompt verbatim with nothing injected", () => {
    const out = assemblePrompt(cfg({ system_prompt_mode: "replace", system_prompt: "RAW PROMPT ONLY" }), toolSpecs);
    expect(out).toBe("RAW PROMPT ONLY");
    expect(out).not.toContain("## SYSTEM");
    expect(out).not.toContain("read_file");
  });

  it("augment mode reflects tool changes", () => {
    const out = assemblePrompt(cfg({ tools: ["read_file"] }), toolSpecs);
    expect(out).toContain("read_file");
    expect(out).not.toContain("web_fetch");
  });
});
