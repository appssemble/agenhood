import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Prompts from "./Prompts";

vi.mock("../../api/queries", () => ({
  usePrompts: () => ({
    data: {
      prompts: [
        { id: "prm_1", name: "Weekly status report", body: "Hi {{team}} on {{date}}",
          tags: ["report"], variables: [], created_by: null,
          created_at: "2026-06-24", updated_at: "2026-06-24" },
      ],
    },
    isLoading: false,
  }),
  useDeletePrompt: () => ({ mutateAsync: vi.fn() }),
  useWorkflows: () => ({ data: { workflows: [] } }),
}));

vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

test("renders prompt cards with name and its variables", () => {
  render(<MemoryRouter><Prompts /></MemoryRouter>);
  expect(screen.getByText("Weekly status report")).toBeInTheDocument();
  // variables are surfaced as distinct {{name}} chips
  expect(screen.getByText("{{team}}")).toBeInTheDocument();
  expect(screen.getByText("{{date}}")).toBeInTheDocument();
});

test("shows a copy-id control on each card", () => {
  render(<MemoryRouter><Prompts /></MemoryRouter>);
  expect(screen.getByRole("button", { name: /copy.*prm_1/i })).toBeInTheDocument();
});
