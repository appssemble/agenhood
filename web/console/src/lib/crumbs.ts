export interface Crumb {
  label: string;
  to?: string;
  bold?: boolean;
}

const SECTION_LABELS: Record<string, string> = {
  config: "Configuration",
  files: "Files",
  snapshots: "Snapshots",
  submit: "Submit Task",
  history: "History",
  tasks: "Task",
};

export function buildCrumbs(
  pathname: string,
  containerName?: string | null,
  cid?: string | null,
  workflowName?: string | null,
): Crumb[] {
  if (pathname === "/containers") return [{ label: "Containers", bold: true }];
  if (pathname.startsWith("/containers/new")) {
    return [{ label: "Containers", to: "/containers" }, { label: "New", bold: true }];
  }
  if (pathname.startsWith("/containers/") && cid) {
    const name = containerName ?? cid;
    const rest = pathname.slice(`/containers/${cid}`.length).replace(/^\//, "");
    const seg = rest.split("/")[0];
    if (!seg) {
      return [{ label: "Containers", to: "/containers" }, { label: name, bold: true }];
    }
    return [
      { label: "Containers", to: "/containers" },
      { label: name, to: `/containers/${cid}` },
      { label: SECTION_LABELS[seg] ?? seg, bold: true },
    ];
  }
  if (pathname.startsWith("/tasks")) return [{ label: "Tasks", bold: true }];
  // Workflows: the list, and the details hub at /workflows/:id (exact — not
  // /new, /:id/edit or /:id/runs/:runId, which keep their own in-page headers).
  if (pathname === "/workflows") return [{ label: "Workflows", bold: true }];
  {
    const wfm = pathname.match(/^\/workflows\/([^/]+)$/);
    if (wfm && wfm[1] !== "new") {
      return [
        { label: "Workflows", to: "/workflows" },
        { label: workflowName ?? wfm[1], bold: true },
      ];
    }
  }
  // Templates & Skills live in the Fleet section (not Settings), so they show no
  // Settings parent — matching how other Fleet pages (Containers, Tasks) crumb.
  if (pathname === "/settings/templates") return [{ label: "Templates", bold: true }];
  if (pathname === "/settings/skills") return [{ label: "Skills", bold: true }];
  if (pathname === "/settings/mcp") return [{ label: "MCP servers", bold: true }];
  if (pathname.startsWith("/settings/templates/")) {
    const leaf = pathname.split("/").pop() ?? "";
    return [
      { label: "Templates", to: "/settings/templates" },
      { label: leaf === "new" ? "New" : "Edit", bold: true },
    ];
  }
  if (pathname.startsWith("/settings/")) {
    const leaf = pathname.split("/").pop() ?? "";
    return [{ label: "Settings" }, { label: leaf.replace(/-/g, " "), bold: true }];
  }
  if (pathname.startsWith("/staff")) return [{ label: "Staff", bold: true }];
  return [{ label: "Dashboard", bold: true }];
}
