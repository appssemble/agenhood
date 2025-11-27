import { render, screen } from "@testing-library/react";
import { OneTimeSecret } from "./OneTimeSecret";

test("shows the secret once with a copy button and warning", () => {
  render(<OneTimeSecret secret="ahd_live_abc" onDismiss={() => {}} />);
  expect(screen.getByText("ahd_live_abc")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  expect(screen.getByText(/won't see it again/i)).toBeInTheDocument();
});
