import { Icons } from "../ui/Icon";

// Representative icon per built-in driver (one built-in template exists per
// driver). Unknown drivers fall back to the generic Star.
const DRIVER_ICON: Record<string, typeof Icons.Star> = {
  vanilla: Icons.Cube, // barebones — a minimal building block
  opencode: Icons.Code, // open-source coding agent
  codex: Icons.Bot, // OpenAI Codex agent
  api: Icons.Bolt, // direct single-call driver — fast, no tools
};
export const driverIcon = (d: string) => DRIVER_ICON[d] ?? Icons.Star;

// Console-facing display name per driver (the backend driver id is unchanged).
const DRIVER_LABEL: Record<string, string> = {
  vanilla: "barebones",
  api: "api",
};
export const driverLabel = (d: string) => DRIVER_LABEL[d] ?? d;

// One-line description shown on the driver picker cards.
const DRIVER_DESC: Record<string, string> = {
  vanilla: "Minimal agent. You pick the tools, skills, and MCP servers, and write the prompt.",
  opencode: "Coding agent that manages its own tools and context.",
  codex: "OpenAI Codex agent with support for attached skills.",
  api: "Direct single-call driver. No tools — one LLM API call per task, built for many parallel tasks per container.",
};
export const driverDesc = (d: string) => DRIVER_DESC[d] ?? "Configurable agent driver.";
