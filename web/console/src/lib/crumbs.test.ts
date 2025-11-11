import { describe, it, expect } from "vitest";
import { buildCrumbs } from "./crumbs";

describe("buildCrumbs", () => {
  it("dashboard root", () => {
    expect(buildCrumbs("/", null, null)).toEqual([{ label: "Dashboard", bold: true }]);
  });
  it("containers list", () => {
    expect(buildCrumbs("/containers", null, null)).toEqual([{ label: "Containers", bold: true }]);
  });
  it("new container links back to the list", () => {
    expect(buildCrumbs("/containers/new", null, null)).toEqual([
      { label: "Containers", to: "/containers" },
      { label: "New", bold: true },
    ]);
  });
  it("container root: Containers link + bold name", () => {
    expect(buildCrumbs("/containers/cnt_1", "web-support", "cnt_1")).toEqual([
      { label: "Containers", to: "/containers" },
      { label: "web-support", bold: true },
    ]);
  });
  it("container sub-route: Containers link + name link + bold section", () => {
    expect(buildCrumbs("/containers/cnt_1/config", "web-support", "cnt_1")).toEqual([
      { label: "Containers", to: "/containers" },
      { label: "web-support", to: "/containers/cnt_1" },
      { label: "Configuration", bold: true },
    ]);
  });
  it("tasks, settings, staff", () => {
    expect(buildCrumbs("/tasks", null, null)).toEqual([{ label: "Tasks", bold: true }]);
    expect(buildCrumbs("/settings/api-keys", null, null)).toEqual([
      { label: "Settings" },
      { label: "api keys", bold: true },
    ]);
    expect(buildCrumbs("/staff", null, null)).toEqual([{ label: "Staff", bold: true }]);
  });
  it("templates and skills live in Fleet, not Settings", () => {
    expect(buildCrumbs("/settings/templates", null, null)).toEqual([{ label: "Templates", bold: true }]);
    expect(buildCrumbs("/settings/skills", null, null)).toEqual([{ label: "Skills", bold: true }]);
  });
  it("crumbs MCP servers as a Fleet leaf", () => {
    expect(buildCrumbs("/settings/mcp", null, null)).toEqual([{ label: "MCP servers", bold: true }]);
  });
  it("workflows list and details hub", () => {
    expect(buildCrumbs("/workflows", null, null)).toEqual([{ label: "Workflows", bold: true }]);
    // /workflows/:id exactly → Workflows link + bold workflow name
    expect(buildCrumbs("/workflows/wf_1", null, null, "Release Notes Bot")).toEqual([
      { label: "Workflows", to: "/workflows" },
      { label: "Release Notes Bot", bold: true },
    ]);
    // falls back to the id when the name hasn't loaded yet
    expect(buildCrumbs("/workflows/wf_1", null, null, null)).toEqual([
      { label: "Workflows", to: "/workflows" },
      { label: "wf_1", bold: true },
    ]);
  });
  it("workflow new/edit/runs are NOT treated as the details hub", () => {
    // these keep their own in-page headers, so buildCrumbs leaves them to the fallback
    expect(buildCrumbs("/workflows/new", null, null)).toEqual([{ label: "Dashboard", bold: true }]);
    expect(buildCrumbs("/workflows/wf_1/edit", null, null, "X")).toEqual([{ label: "Dashboard", bold: true }]);
    expect(buildCrumbs("/workflows/wf_1/runs/wfr_1", null, null, "X")).toEqual([{ label: "Dashboard", bold: true }]);
  });
  it("template create/edit link back to the templates list", () => {
    expect(buildCrumbs("/settings/templates/new", null, null)).toEqual([
      { label: "Templates", to: "/settings/templates" },
      { label: "New", bold: true },
    ]);
    expect(buildCrumbs("/settings/templates/tpl_1/edit", null, null)).toEqual([
      { label: "Templates", to: "/settings/templates" },
      { label: "Edit", bold: true },
    ]);
  });
});
