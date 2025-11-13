import { buildItems, filterItems } from "./commandItems";
import type { Container, Template } from "../api/types";

const containers = [{ id: "ctr_1", name: "research-prod", status: "running", external_id: null }] as Container[];
const templates = [{ id: "tpl_1", name: "Research assistant", driver: "vanilla" }] as Template[];

test("buildItems includes containers, templates, and static actions", () => {
  const items = buildItems(containers, templates);
  expect(items.some((i) => i.kind === "container" && i.id === "ctr_1")).toBe(true);
  expect(items.some((i) => i.kind === "template")).toBe(true);
  expect(items.some((i) => i.kind === "action" && i.to === "/containers/new")).toBe(true);
});

it("includes Dashboard and Tasks navigation actions", () => {
  const items = buildItems([], []);
  const actions = items.filter((i) => i.kind === "action");
  expect(actions.find((a) => a.label === "Dashboard")?.to).toBe("/");
  expect(actions.find((a) => a.label === "Tasks")?.to).toBe("/tasks");
});

test("filterItems matches by label substring, case-insensitive", () => {
  const items = buildItems(containers, templates);
  const r = filterItems(items, "research");
  expect(r.length).toBeGreaterThanOrEqual(2);
  expect(filterItems(items, "zzz")).toHaveLength(0);
});
