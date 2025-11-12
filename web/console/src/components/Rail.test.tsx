import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Rail } from "./Rail";
import type { Me } from "../api/types";

const member = { name: "Mara", role: "member", is_staff: false } as Me;
const staff = { name: "Stan", role: "admin", is_staff: true } as Me;

test("renders Dashboard, Fleet, Tasks, Settings for everyone; Staff only for staff", () => {
  const { rerender } = render(
    <MemoryRouter><Rail user={member} section="dashboard" /></MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: "Fleet" })).toHaveAttribute("href", "/containers");
  expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings/users");
  expect(screen.getByRole("link", { name: "Profile" })).toHaveAttribute("href", "/profile");
  expect(screen.queryByRole("link", { name: "Staff" })).toBeNull();

  rerender(<MemoryRouter><Rail user={staff} section="staff" /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Staff" })).toHaveAttribute("href", "/staff");
});

test("marks the active section", () => {
  render(<MemoryRouter><Rail user={member} section="tasks" /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Tasks" }).className).toContain("active");
  expect(screen.getByRole("link", { name: "Fleet" }).className).not.toContain("active");
});
