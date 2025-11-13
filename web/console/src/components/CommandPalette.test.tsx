import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CommandPalette } from "./CommandPalette";
import type { Container, Template } from "../api/types";

const containers = [{ id: "ctr_1", name: "research-prod", status: "running", external_id: null }] as Container[];

test("filters as you type and navigates on Enter", async () => {
  const onClose = vi.fn();
  render(<MemoryRouter><CommandPalette open onClose={onClose} containers={containers} templates={[] as Template[]} /></MemoryRouter>);
  const input = screen.getByPlaceholderText(/jump to/i);
  await userEvent.type(input, "research");
  expect(screen.getByText("research-prod")).toBeInTheDocument();
  await userEvent.keyboard("{Enter}");
  expect(onClose).toHaveBeenCalled();
});

test("Escape closes", async () => {
  const onClose = vi.fn();
  render(<MemoryRouter><CommandPalette open onClose={onClose} containers={[]} templates={[]} /></MemoryRouter>);
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});
