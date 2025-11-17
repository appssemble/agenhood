import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";
import { ConfirmBar } from "./ConfirmBar";

describe("ConfirmDialog", () => {
  it("invokes onConfirm and onCancel", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn(); const onCancel = vi.fn();
    render(<ConfirmDialog open title="Destroy container" body="permanent" confirmLabel="Destroy" onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("Destroy container");
    await user.click(screen.getByRole("button", { name: "Destroy" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
  it("renders nothing when closed", () => {
    render(<ConfirmDialog open={false} title="x" body="y" confirmLabel="z" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("ConfirmBar", () => {
  it("renders an inline confirm with confirm/keep actions", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmBar message="Cancel this task?" confirmLabel="Yes, cancel task" cancelLabel="Keep running" onConfirm={onConfirm} onCancel={() => {}} />);
    expect(screen.getByText("Cancel this task?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Yes, cancel task" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
