import { render, screen } from "@testing-library/react";
import { Card, CardHead } from "./Card";

test("Card renders children; flush adds flush class", () => {
  const { rerender } = render(<Card>body</Card>);
  expect(screen.getByText("body").className).toMatch(/\bcard\b/);
  rerender(<Card flush>body</Card>);
  expect(screen.getByText("body").className).toMatch(/\bflush\b/);
});

test("CardHead renders a heading slot", () => {
  render(<CardHead><h3>Title</h3></CardHead>);
  expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
});
