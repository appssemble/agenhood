import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiRow } from "./KpiRow";

describe("KpiRow", () => {
  it("renders compact tokens, task count, success %, iterations", () => {
    render(<KpiRow totals={{ tokens: 6_000_000, tasks: 248, successRate: 0.93, iterations: 1540 }} />);
    expect(screen.getByTestId("kpi-tokens")).toHaveTextContent("6.0M");
    expect(screen.getByTestId("kpi-tasks")).toHaveTextContent("248");
    expect(screen.getByTestId("kpi-success")).toHaveTextContent("93%");
    expect(screen.getByTestId("kpi-iterations")).toHaveTextContent("1,540");
  });

  it("shows a dash for success when there are no tasks", () => {
    render(<KpiRow totals={{ tokens: 0, tasks: 0, successRate: null, iterations: 0 }} />);
    expect(screen.getByTestId("kpi-success")).toHaveTextContent("—");
  });
});
