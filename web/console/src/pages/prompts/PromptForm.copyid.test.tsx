import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../../api/queries", () => ({
  fetchPrompt: vi.fn().mockResolvedValue({
    id: "prm_edit_9", name: "P", body: "Hi {{x}}", tags: [],
    variables: [{ name: "x", label: "", default: "" }],
    created_by: null, created_at: "2026-06-25", updated_at: "2026-06-25",
  }),
  useSavePrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import PromptForm from "./PromptForm";

describe("PromptForm edit header", () => {
  it("shows a copy-id control when editing", async () => {
    render(
      <MemoryRouter initialEntries={["/prompts/prm_edit_9/edit"]}>
        <Routes>
          <Route path="/prompts/:id/edit" element={<PromptForm />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: /copy.*prm_edit_9/i })).toBeInTheDocument();
  });
});
