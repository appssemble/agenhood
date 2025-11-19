import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/render";
import { RangeToggle } from "./RangeToggle";

describe("RangeToggle", () => {
  it("defaults to 7d and renders all options", () => {
    renderWithProviders(<RangeToggle />);
    for (const label of ["24h", "7d", "30d"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "7d" }).className).toMatch(/active/);
  });

  it("reads the active range from the URL ?range param", () => {
    renderWithProviders(<RangeToggle />, { route: "/?range=24h" });
    expect(screen.getByRole("button", { name: "24h" }).className).toMatch(/active/);
  });

  it("selecting a range updates the URL", async () => {
    renderWithProviders(<RangeToggle />, { route: "/?range=7d" });
    await userEvent.click(screen.getByRole("button", { name: "30d" }));
    expect(screen.getByRole("button", { name: "30d" }).className).toMatch(/active/);
  });
});
