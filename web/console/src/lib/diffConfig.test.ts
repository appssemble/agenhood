import { diffConfig } from "./diffConfig";
import type { AgentConfig } from "../api/types";

const base: AgentConfig = { driver: "vanilla", model: "sonnet-4.5", system_prompt: "x",
  system_prompt_mode: "augment", tools: ["read_file"], context: { variables: {}, text: null, files: [] } };

test("flags changed mode, added/removed tools, same driver", () => {
  const cur = { ...base, system_prompt_mode: "replace" as const, tools: ["read_file", "run_python"] };
  const rows = diffConfig(base, cur);
  expect(rows.find((r) => r.key === "Driver")!.state).toBe("same");
  expect(rows.find((r) => r.key === "Prompt mode")!.state).toBe("changed");
  expect(rows.find((r) => r.key === "Tools · run_python")!.state).toBe("added");
});
