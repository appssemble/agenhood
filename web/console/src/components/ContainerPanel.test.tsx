import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ContainerPanel } from "./ContainerPanel";
import type { Container } from "../api/types";

const containers = [
  { id: "cnt_1", name: "web-support", external_id: "cnt_1", status: "running", image_variant: "full", config: { driver: "opencode", model: "claude-sonnet-4-6" } } as Container,
];

test("renders the container sub-nav with stable accessible names", () => {
  render(<MemoryRouter><ContainerPanel containers={containers} cid="cnt_1" /></MemoryRouter>);
  for (const name of ["Overview", "Configuration", "Files", "Snapshots", "Submit Task", "History"]) {
    expect(screen.getByRole("link", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "Configuration" })).toHaveAttribute("href", "/containers/cnt_1/config");
  expect(screen.getByRole("link", { name: "Submit Task" })).toHaveAttribute("href", "/containers/cnt_1/submit");
});

test("includes the switcher for the active container", () => {
  render(<MemoryRouter><ContainerPanel containers={containers} cid="cnt_1" /></MemoryRouter>);
  expect(screen.getByRole("button", { name: /web-support/ })).toBeInTheDocument();
});
