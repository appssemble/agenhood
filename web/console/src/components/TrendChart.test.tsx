import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrendChart } from "./TrendChart";
import type { UsageSeriesPoint } from "../api/types";

const series: UsageSeriesPoint[] = [
  { start: "2026-05-27T00:00:00+00:00", tokens_in: 520000, tokens_out: 210000, tasks: 34, iterations: 198 },
  { start: "2026-05-28T00:00:00+00:00", tokens_in: 610000, tokens_out: 260000, tasks: 41, iterations: 233 },
];

describe("TrendChart", () => {
  it("renders the chart container and a custom legend", () => {
    render(<TrendChart series={series} interval="day" />);
    expect(screen.getByTestId("trend-chart")).toBeInTheDocument();
    expect(screen.getByText("tokens in")).toBeInTheDocument();
    expect(screen.getByText("tokens out")).toBeInTheDocument();
  });

  it("renders without crashing on an empty series", () => {
    render(<TrendChart series={[]} interval="day" />);
    expect(screen.getByTestId("trend-chart")).toBeInTheDocument();
  });
});
