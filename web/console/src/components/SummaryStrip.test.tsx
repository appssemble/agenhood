import { render, screen } from "@testing-library/react";
import { SummaryStrip } from "./SummaryStrip";
import type { Container } from "../api/types";

const c = { id: "ctr_9f3a26", name: "research-prod", external_id: "ctr_9f3a26", status: "running", image_variant: "full",
  config: { driver: "vanilla", model: "sonnet-4.5" } } as Container;

test("shows identity, status, driver/model, variant, and derived stats", () => {
  render(<SummaryStrip container={c} running={2} tokensToday={342891} />);
  expect(screen.getByText("research-prod")).toBeInTheDocument();
  expect(screen.getByText(/vanilla/)).toBeInTheDocument();
  expect(screen.getByText("342,891")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
});
