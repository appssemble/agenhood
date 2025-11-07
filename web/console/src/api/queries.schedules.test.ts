import { keys } from "./queries";

test("scheduled tasks are tenant-scoped keys", () => {
  expect(keys.scheduledTasks()).toEqual(["scheduled-tasks"]);
  expect(keys.scheduledTask("sch_1")).toEqual(["scheduled-tasks", "sch_1"]);
});
