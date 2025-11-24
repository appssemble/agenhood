import { render, screen } from "@testing-library/react";
import { TokenMeter } from "./TokenMeter";

test("shows percent and danger tone past 90%", () => {
  render(<TokenMeter used={115000} cap={120000} />);
  expect(screen.getByText(/115,000/)).toBeInTheDocument();
  expect(screen.getByTestId("meter-fill").className).toMatch(/danger/);
});

test("no cap → counter only, no fill bar", () => {
  render(<TokenMeter used={5000} />);
  expect(screen.getByText(/5,000/)).toBeInTheDocument();
  expect(screen.queryByTestId("meter-fill")).toBeNull();
});
