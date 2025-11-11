import { describe, it, expect } from "vitest";
import { deriveNav } from "./navSection";

describe("deriveNav", () => {
  it("maps the dashboard root to its own rail section (sharing the fleet panel)", () => {
    expect(deriveNav("/")).toEqual({ rail: "dashboard", panel: "fleet", cid: null });
  });
  it("maps the containers list and new-container to fleet", () => {
    expect(deriveNav("/containers")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/containers/new")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("maps a specific container (and its sub-routes) to the container panel, keeping the fleet rail lit", () => {
    expect(deriveNav("/containers/cnt_7f3a")).toEqual({ rail: "fleet", panel: "container", cid: "cnt_7f3a" });
    expect(deriveNav("/containers/cnt_7f3a/config")).toEqual({ rail: "fleet", panel: "container", cid: "cnt_7f3a" });
    expect(deriveNav("/containers/cnt_7f3a/tasks/tsk_1")).toEqual({ rail: "fleet", panel: "container", cid: "cnt_7f3a" });
  });
  it("maps Templates, Skills and MCP servers to the Fleet section (they live above Containers)", () => {
    expect(deriveNav("/settings/templates")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/settings/skills")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/settings/mcp")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("keeps the Fleet rail lit on the MCP server create/edit sub-routes", () => {
    expect(deriveNav("/settings/mcp/new")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/settings/mcp/mcp_1/edit")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("keeps the Fleet rail lit on the template create/edit sub-routes", () => {
    expect(deriveNav("/settings/templates/new")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/settings/templates/tpl_1/edit")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("keeps the Fleet rail lit on the skill create/edit sub-routes", () => {
    expect(deriveNav("/settings/skills/new")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
    expect(deriveNav("/settings/skills/skl_1/edit")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("maps tasks, settings, and staff to their own sections", () => {
    expect(deriveNav("/tasks")).toEqual({ rail: "tasks", panel: "tasks", cid: null });
    expect(deriveNav("/settings/users")).toEqual({ rail: "settings", panel: "settings", cid: null });
    expect(deriveNav("/staff")).toEqual({ rail: "staff", panel: "staff", cid: null });
  });
  it("maps profile to its own rail section with no secondary panel", () => {
    expect(deriveNav("/profile")).toEqual({ rail: "profile", panel: "fleet", cid: null });
  });
  it("falls back to fleet for anything unknown", () => {
    expect(deriveNav("/whatever")).toEqual({ rail: "fleet", panel: "fleet", cid: null });
  });
  it("maps /prompts to the workflows rail", () => {
    expect(deriveNav("/prompts").rail).toBe("workflows");
  });
  it("keeps workflows rail on prompts editor sub-routes", () => {
    expect(deriveNav("/prompts/new").rail).toBe("workflows");
    expect(deriveNav("/prompts/prm_123/edit").rail).toBe("workflows");
  });
  it("prompts and workflows both map to the workflows rail", () => {
    expect(deriveNav("/prompts").rail).toBe("workflows");
    expect(deriveNav("/workflows").rail).toBe("workflows");
  });
});
