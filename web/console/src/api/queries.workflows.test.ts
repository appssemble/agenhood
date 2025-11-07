import { keys } from "./queries";

test("workflow query keys are namespaced", () => {
  expect(keys.workflows).toEqual(["workflows"]);
  expect(keys.workflow("wf_1")).toEqual(["workflows", "wf_1"]);
  expect(keys.workflowRuns("wf_1")).toEqual(["workflows", "wf_1", "runs"]);
});
