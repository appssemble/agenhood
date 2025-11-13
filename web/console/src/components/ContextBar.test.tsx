import { screen, fireEvent } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { ContextBar } from "./ContextBar";
import { renderWithProviders } from "../test/render";

function Loc() { return <div data-testid="loc">{useLocation().pathname}</div>; }

test("renders breadcrumbs and triggers the command palette", () => {
  const onOpenPalette = vi.fn();
  renderWithProviders(
    <ContextBar crumbs={[{ label: "Dashboard", bold: true }]} runningCount={0} onOpenPalette={onOpenPalette} onToggleApiLog={() => {}} apiLogOpen={false} onToggleNav={() => {}} />,
  );
  expect(screen.getByText("Dashboard")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /jump to/i }));
  expect(onOpenPalette).toHaveBeenCalledOnce();
});

test("running indicator shows the count and links to /tasks; hidden when zero", () => {
  const { rerender } = renderWithProviders(
    <><ContextBar crumbs={[]} runningCount={0} onOpenPalette={() => {}} onToggleApiLog={() => {}} apiLogOpen={false} onToggleNav={() => {}} /><Loc /></>,
  );
  expect(screen.queryByRole("button", { name: /running/i })).toBeNull();

  rerender(
    <><ContextBar crumbs={[]} runningCount={2} onOpenPalette={() => {}} onToggleApiLog={() => {}} apiLogOpen={false} onToggleNav={() => {}} /><Loc /></>,
  );
  const ind = screen.getByRole("button", { name: /2 running/i });
  fireEvent.click(ind);
  expect(screen.getByTestId("loc").textContent).toBe("/tasks");
});
