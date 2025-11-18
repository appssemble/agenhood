import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DriverPicker } from "./DriverPicker";

describe("DriverPicker", () => {
  it("renders one card per driver, labelled with the display name", () => {
    render(<DriverPicker value="vanilla" drivers={["vanilla", "opencode", "codex"]} onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "barebones" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "opencode" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "codex" })).toBeInTheDocument();
  });

  it("marks the selected driver via aria-checked", () => {
    render(<DriverPicker value="opencode" drivers={["vanilla", "opencode"]} onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "opencode" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "barebones" })).toHaveAttribute("aria-checked", "false");
  });

  it("calls onChange with the raw driver id when a card is clicked", async () => {
    const onChange = vi.fn();
    render(<DriverPicker value="vanilla" drivers={["vanilla", "opencode"]} onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "opencode" }));
    expect(onChange).toHaveBeenCalledWith("opencode");
  });

  it("moves selection with arrow keys (roving)", async () => {
    const onChange = vi.fn();
    render(<DriverPicker value="vanilla" drivers={["vanilla", "opencode", "codex"]} onChange={onChange} />);
    screen.getByRole("radio", { name: "barebones" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("opencode");
  });

  it("uses roving tabindex (only the selected card is in tab order)", () => {
    render(<DriverPicker value="opencode" drivers={["vanilla", "opencode"]} onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "opencode" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "barebones" })).toHaveAttribute("tabindex", "-1");
  });
});
