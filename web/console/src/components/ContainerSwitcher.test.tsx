import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ContainerSwitcher } from "./ContainerSwitcher";
import type { Container } from "../api/types";

function mk(id: string, name: string, status = "running"): Container {
  return { id, name, external_id: id, status, image_variant: "full", config: { driver: "opencode", model: "claude-sonnet-4-6" } } as Container;
}
const containers = [mk("cnt_1", "web-support"), mk("cnt_2", "qa-runner"), mk("cnt_3", "billing-agent", "paused")];

function Loc() { return <div data-testid="loc">{useLocation().pathname}</div>; }

test("shows the active container name and opens the list", () => {
  render(<MemoryRouter><ContainerSwitcher containers={containers} activeId="cnt_1" /></MemoryRouter>);
  expect(screen.getByRole("button", { name: /web-support/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /web-support/ }));
  expect(screen.getByText("qa-runner")).toBeInTheDocument();
  expect(screen.getByText("billing-agent")).toBeInTheDocument();
});

test("filters by query", () => {
  render(<MemoryRouter><ContainerSwitcher containers={containers} activeId="cnt_1" /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: /web-support/ }));
  fireEvent.change(screen.getByPlaceholderText(/switch container/i), { target: { value: "qa" } });
  expect(screen.getByText("qa-runner")).toBeInTheDocument();
  expect(screen.queryByText("billing-agent")).toBeNull();
});

test("selecting a container navigates to it", () => {
  render(
    <MemoryRouter initialEntries={["/containers/cnt_1"]}>
      <ContainerSwitcher containers={containers} activeId="cnt_1" />
      <Loc />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /web-support/ }));
  fireEvent.click(screen.getByText("qa-runner"));
  expect(screen.getByTestId("loc").textContent).toBe("/containers/cnt_2");
});
