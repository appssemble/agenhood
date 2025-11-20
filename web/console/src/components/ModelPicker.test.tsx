import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { ModelPicker } from "./ModelPicker";

function models() {
  return { models: [
    { id: "opencode/zen-free", provider: "opencode", label: "Zen Free", category: "free", drivers: ["opencode"], available: true, requires: [] },
    { id: "anthropic/claude-opus-4-8", provider: "anthropic", label: "Claude Opus 4.8", category: "api_key", drivers: ["opencode","vanilla"], available: true, requires: [] },
    { id: "openai/gpt-5.4", provider: "openai", label: "GPT-5.4", category: "api_key", drivers: ["opencode"], available: false, requires: ["openai_api_key"] },
  ] };
}

describe("ModelPicker", () => {
  it("renders grouped models with availability badges", async () => {
    server.use(http.get("/v1/models", () => HttpResponse.json(models())));
    renderWithProviders(<ModelPicker driver="opencode" value="" onChange={() => {}} />);
    expect(await screen.findByText("Claude Opus 4.8")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.4")).toBeInTheDocument();
    // unavailable model shows a needs-credential badge
    expect(screen.getByText(/needs OpenAI key/i)).toBeInTheDocument();
  });

  it("selecting a model calls onChange with its id", async () => {
    server.use(http.get("/v1/models", () => HttpResponse.json(models())));
    const onChange = vi.fn();
    renderWithProviders(<ModelPicker driver="opencode" value="" onChange={onChange} />);
    await userEvent.click(await screen.findByText("Claude Opus 4.8"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("anthropic/claude-opus-4-8"));
  });
});
