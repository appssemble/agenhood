import { render, screen } from "@testing-library/react";
import { EmptyState, EmptyRow } from "./EmptyState";

test("EmptyState renders title, description, named icon and actions", () => {
  const { container } = render(
    <EmptyState
      icon="Key"
      title="No API keys yet"
      description="Create a key to get started."
      actions={<button>New key</button>}
    />,
  );
  expect(screen.getByText("No API keys yet")).toBeInTheDocument();
  expect(screen.getByText("Create a key to get started.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New key" })).toBeInTheDocument();
  expect(container.querySelector(".empty-md .empty-ico svg")).toBeInTheDocument();
});

test("EmptyState size sm applies the compact modifier", () => {
  const { container } = render(<EmptyState size="sm" title="No usage" />);
  expect(container.querySelector(".empty.empty-sm")).toBeInTheDocument();
});

test("EmptyRow wraps an EmptyState in a full-width table cell", () => {
  const { container } = render(
    <table>
      <tbody>
        <EmptyRow colSpan={4} icon="Tasks" title="No tasks yet" />
      </tbody>
    </table>,
  );
  const cell = container.querySelector("td.empty-cell");
  expect(cell).toHaveAttribute("colspan", "4");
  expect(screen.getByText("No tasks yet")).toBeInTheDocument();
});
