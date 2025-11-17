import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../lib/clipboard", () => ({ copyText: vi.fn().mockResolvedValue(true) }));
import { copyText } from "../lib/clipboard";
import { CopyId } from "./CopyId";

describe("CopyId", () => {
  it("copies the full id and shows Copied", async () => {
    render(<CopyId id="prm_full_123" />);
    const btn = screen.getByRole("button", { name: /copy.*prm_full_123/i });
    await userEvent.click(btn);
    expect(copyText).toHaveBeenCalledWith("prm_full_123");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("shows a short label but still copies the full id", async () => {
    render(<CopyId id="prm_full_123" label="prm_…123" />);
    const btn = screen.getByRole("button", { name: /copy.*prm_full_123/i });
    expect(screen.getByText("prm_…123")).toBeInTheDocument();
    await userEvent.click(btn);
    expect(copyText).toHaveBeenCalledWith("prm_full_123");
  });
});
