import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Breadcrumbs } from "./Breadcrumbs";

test("renders a link for segments with `to`, plain text otherwise, bold leaf", () => {
  render(
    <MemoryRouter>
      <Breadcrumbs items={[
        { label: "Containers", to: "/containers" },
        { label: "web-support", to: "/containers/cnt_1" },
        { label: "Configuration", bold: true },
      ]} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Containers" })).toHaveAttribute("href", "/containers");
  expect(screen.getByRole("link", { name: "web-support" })).toHaveAttribute("href", "/containers/cnt_1");
  // leaf is not a link
  expect(screen.queryByRole("link", { name: "Configuration" })).toBeNull();
  expect(screen.getByText("Configuration")).toBeInTheDocument();
});
