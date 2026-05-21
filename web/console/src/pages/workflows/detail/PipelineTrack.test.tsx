import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { PipelineTrack } from "./PipelineTrack";
import type { PipelineStepVM } from "./derive";

const VMS: PipelineStepVM[] = [
  { index: 0, promptName: "Summarize", promptId: "prm_a", containerName: "builder", varCount: 2, status: "completed", durationLabel: "48s" },
  { index: 1, promptName: "Draft", promptId: "prm_b", containerName: "writer", varCount: 1, status: "running", durationLabel: "1m" },
];

describe("PipelineTrack", () => {
  test("renders each step with prompt name and fires onSelect", () => {
    const onSelect = vi.fn();
    render(<PipelineTrack steps={VMS} selectedIndex={null} onSelect={onSelect} />);
    expect(screen.getByText("Summarize")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Step 1: Summarize/i }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });
});
