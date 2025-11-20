import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/render";
import { TopContainers } from "./TopContainers";
import type { BreakdownGroup } from "../api/types";

const groups: BreakdownGroup[] = [
  { key: "c2", label: "code-reviewer", tokens_in: 900000, tokens_out: 300000, tasks: 48, iterations: 1 },
  { key: "c1", label: "support-bot", tokens_in: 1400000, tokens_out: 500000, tasks: 62, iterations: 1 },
];

describe("TopContainers", () => {
  it("ranks by total tokens descending", () => {
    renderWithProviders(<TopContainers groups={groups} />);
    const names = screen.getAllByTestId("lb-name").map((n) => n.textContent);
    expect(names).toEqual(["support-bot", "code-reviewer"]);
  });

  it("shows an empty message when there is no usage", () => {
    renderWithProviders(<TopContainers groups={[]} />);
    expect(screen.getByText(/no usage in this range/i)).toBeInTheDocument();
  });
});
