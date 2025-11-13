import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";

describe("CreateWorkspaceDialog", () => {
  it("disables Create until a name is entered, then creates and reports the new id", async () => {
    server.use(http.post("/v1/tenants", async ({ request }) => {
      const b = (await request.json()) as { name: string };
      return HttpResponse.json({ id: "ten_new", name: b.name, owner_id: "usr_s" });
    }));
    const onCreated = vi.fn();
    renderWithProviders(
      <CreateWorkspaceDialog open onClose={() => {}} onCreated={onCreated} />,
    );
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Workspace name"), "Acme Corp");
    expect(create).toBeEnabled();
    await userEvent.click(create);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("ten_new", "Acme Corp"));
  });

  it("dismisses when the backdrop is clicked, but not when the card is clicked", () => {
    const onClose = vi.fn();
    renderWithProviders(
      <CreateWorkspaceDialog open onClose={onClose} onCreated={() => {}} />,
    );
    // Clicking inside the card does NOT close.
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    // The overlay is portaled to <body>, so query it from the document.
    fireEvent.mouseDown(document.querySelector(".cw-overlay")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when closed", () => {
    renderWithProviders(
      <CreateWorkspaceDialog open={false} onClose={() => {}} onCreated={() => {}} />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
