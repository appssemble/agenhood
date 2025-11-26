import { render, screen } from "@testing-library/react";
import { ConfigDiff } from "./ConfigDiff";
import type { AgentConfig } from "../api/types";

const base: AgentConfig = { driver: "vanilla", model: "sonnet-4.5", system_prompt: "x",
  system_prompt_mode: "augment", tools: ["read_file"], context: { variables: {}, text: null, files: [] } };

test("renders changed rows", () => {
  const cur = { ...base, system_prompt_mode: "replace" as const };
  render(<ConfigDiff snapshot={base} current={cur} />);
  expect(screen.getByText("Prompt mode")).toBeInTheDocument();
});
