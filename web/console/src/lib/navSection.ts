export type RailSection = "dashboard" | "fleet" | "tasks" | "workflows" | "settings" | "staff" | "profile";
export type PanelMode = "fleet" | "tasks" | "workflows" | "settings" | "staff" | "container";

export interface NavState {
  rail: RailSection;
  panel: PanelMode;
  cid: string | null;
}

export function deriveNav(pathname: string): NavState {
  // Dashboard is its own top-level rail item; it shares the fleet (container-list) panel.
  if (pathname === "/") return { rail: "dashboard", panel: "fleet", cid: null };
  // Templates & Skills live in the Fleet section (above Containers); routes stay under /settings.
  // Include the template create/edit sub-routes (/settings/templates/new, /:id/edit) so the rail
  // stays on Fleet while authoring a template instead of falling through to Settings.
  if (
    pathname === "/settings/templates" ||
    pathname.startsWith("/settings/templates/") ||
    pathname === "/settings/skills" ||
    pathname.startsWith("/settings/skills/") ||
    pathname === "/settings/mcp" ||
    pathname.startsWith("/settings/mcp/")
  )
    return { rail: "fleet", panel: "fleet", cid: null };
  const m = pathname.match(/^\/containers\/([^/]+)/);
  if (m && m[1] !== "new") return { rail: "fleet", panel: "container", cid: m[1] };
  if (pathname.startsWith("/tasks")) return { rail: "tasks", panel: "tasks", cid: null };
  // Profile opens from the rail's user avatar; it runs full-width with no secondary panel.
  if (pathname.startsWith("/profile")) return { rail: "profile", panel: "fleet", cid: null };
  // Workflows section: Prompts, Workflows and Scheduled runs, with a secondary nav panel.
  if (
    pathname.startsWith("/prompts") ||
    pathname.startsWith("/workflows") ||
    pathname.startsWith("/schedules")
  )
    return { rail: "workflows", panel: "workflows", cid: null };
  if (pathname.startsWith("/settings")) return { rail: "settings", panel: "settings", cid: null };
  if (pathname.startsWith("/staff")) return { rail: "staff", panel: "staff", cid: null };
  return { rail: "fleet", panel: "fleet", cid: null };
}
