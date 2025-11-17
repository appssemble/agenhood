import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SegControl } from "./SegControl";

test("marks the active option and fires onChange", async () => {
  const onChange = vi.fn();
  render(<SegControl value="all" onChange={onChange}
    options={[{ value: "all", label: "All" }, { value: "running", label: "Running" }]} />);
  expect(screen.getByRole("button", { name: "All" }).className).toMatch(/\bactive\b/);
  await userEvent.click(screen.getByRole("button", { name: "Running" }));
  expect(onChange).toHaveBeenCalledWith("running");
});
