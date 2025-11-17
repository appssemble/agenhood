import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/render";
import { ToastProvider, useToast } from "./Toast";

function Trigger() {
  const toast = useToast();
  return <button onClick={() => toast.error("Couldn't pause container", "Has 2 running tasks.")}>go</button>;
}

describe("Toast", () => {
  it("renders an error toast on demand and dismisses it", async () => {
    const user = userEvent.setup();
    // ToastProvider is already in renderWithProviders; render the trigger inside it.
    renderWithProviders(<ToastProvider><Trigger /></ToastProvider>);
    await user.click(screen.getByText("go"));
    expect(await screen.findByText("Couldn't pause container")).toBeInTheDocument();
    expect(screen.getByText("Has 2 running tasks.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByText("Couldn't pause container")).not.toBeInTheDocument();
  });
});
