import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContainerBadge, TaskBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders each container lifecycle state with its label", () => {
    for (const s of ["running", "paused", "archived", "error", "provisioning", "resuming", "pausing", "destroyed"] as const) {
      const { unmount } = render(<ContainerBadge status={s} />);
      // ContainerBadge maps `archived` to the label "Destroyed" (see LABELS).
      const expected = s === "archived" ? "Destroyed" : s;
      expect(screen.getByText(expected)).toBeInTheDocument();
      unmount();
    }
  });
  it("marks transient states as busy for assistive tech", () => {
    render(<ContainerBadge status="provisioning" />);
    expect(screen.getByText("provisioning").closest("[data-busy]")).toHaveAttribute("data-busy", "true");
  });
  it("applies pill-trans class to transient container states", () => {
    const { unmount } = render(<ContainerBadge status="provisioning" />);
    expect(screen.getByText("provisioning").closest("span")?.className).toMatch(/pill-trans/);
    unmount();
  });
  it("applies pill-running class to running container", () => {
    const { unmount } = render(<ContainerBadge status="running" />);
    expect(screen.getByText("running").closest("span")?.className).toMatch(/pill-running/);
    unmount();
  });
  it("applies pill-error class to error container", () => {
    const { unmount } = render(<ContainerBadge status="error" />);
    expect(screen.getByText("error").closest("span")?.className).toMatch(/pill-error/);
    unmount();
  });
  it("renders task statuses including terminal ones", () => {
    for (const s of ["running", "completed", "failed", "cancelled", "timed_out", "pending"] as const) {
      const { unmount } = render(<TaskBadge status={s} />);
      expect(screen.getByText(s)).toBeInTheDocument();
      unmount();
    }
  });
  it("applies pill-completed class to completed tasks", () => {
    const { unmount } = render(<TaskBadge status="completed" />);
    expect(screen.getByText("completed").closest("span")?.className).toMatch(/pill-completed/);
    unmount();
  });
  it("applies pill-warn class to failed/timed_out tasks", () => {
    const { unmount } = render(<TaskBadge status="failed" />);
    expect(screen.getByText("failed").closest("span")?.className).toMatch(/pill-warn/);
    unmount();
  });
  it("applies pill-cancelled class to cancelled tasks", () => {
    const { unmount } = render(<TaskBadge status="cancelled" />);
    expect(screen.getByText("cancelled").closest("span")?.className).toMatch(/pill-cancelled/);
    unmount();
  });
});
