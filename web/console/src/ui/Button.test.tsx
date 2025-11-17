import { render, screen } from "@testing-library/react";
import { Button } from "./Button";

test("renders children and applies variant + size classes", () => {
  render(<Button variant="primary" size="sm">Save</Button>);
  const btn = screen.getByRole("button", { name: "Save" });
  expect(btn.className).toMatch(/btn-primary/);
  expect(btn.className).toMatch(/btn-sm/);
});

test("forwards onClick and type", () => {
  const fn = vi.fn();
  render(<Button onClick={fn}>Go</Button>);
  screen.getByRole("button", { name: "Go" }).click();
  expect(fn).toHaveBeenCalled();
});
