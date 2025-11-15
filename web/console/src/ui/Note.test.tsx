import { render, screen } from "@testing-library/react";
import { Note } from "./Note";
import { Avatar } from "./Avatar";

test("Note applies tone; Avatar shows initials", () => {
  render(<><Note tone="amber">careful</Note><Avatar name="Davis Lee" /></>);
  expect(screen.getByText("careful").className).toMatch(/\bamber\b/);
  expect(screen.getByText("DL")).toBeInTheDocument();
});
