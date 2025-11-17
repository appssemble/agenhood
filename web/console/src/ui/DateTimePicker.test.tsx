import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { DateTimePicker } from "./DateTimePicker";

test("shows the formatted value on the trigger", () => {
  render(<DateTimePicker value="2026-06-30T09:00" onChange={() => {}} aria-label="Run at" />);
  const trigger = screen.getByLabelText("Run at");
  expect(trigger).toHaveTextContent(/Jun 30, 2026/);
  expect(trigger).toHaveTextContent(/09:00/);
});

test("opens the calendar and emits the picked day in datetime-local format", () => {
  const onChange = vi.fn();
  render(
    <DateTimePicker value="2026-06-30T09:00" onChange={onChange} aria-label="Run at" disablePast={false} />,
  );

  // No calendar until opened
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Run at"));
  expect(screen.getByRole("dialog", { name: /choose date and time/i })).toBeInTheDocument();

  // Pick June 15, 2026 — keeps the existing time (09:00)
  fireEvent.click(screen.getByRole("button", { name: /June 15, 2026/ }));
  expect(onChange).toHaveBeenCalledWith("2026-06-15T09:00");
});

test("changing the time keeps the selected date", () => {
  const onChange = vi.fn();
  render(
    <DateTimePicker value="2026-06-30T09:00" onChange={onChange} aria-label="Run at" disablePast={false} />,
  );
  fireEvent.click(screen.getByLabelText("Run at"));
  fireEvent.change(screen.getByLabelText("Time"), { target: { value: "14:30" } });
  expect(onChange).toHaveBeenCalledWith("2026-06-30T14:30");
});
