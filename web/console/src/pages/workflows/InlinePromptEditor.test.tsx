import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const mutateAsync = vi.fn();
vi.mock("../../api/queries", () => ({ useSavePrompt: () => ({ mutateAsync, isPending: false }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import { InlinePromptEditor } from "./InlinePromptEditor";
import type { Prompt } from "../../api/types";

const PROMPT: Prompt = {
  id: "prm_1", name: "Draft", body: "Hello {{tone}}", tags: ["t"],
  variables: [{ name: "tone", label: "Tone", default: "neutral" }],
  created_by: null, created_at: "", updated_at: "",
};

beforeEach(() => mutateAsync.mockReset());

describe("InlinePromptEditor — edit", () => {
  it("warns about shared usage and saves body+variables under the prompt id", async () => {
    mutateAsync.mockResolvedValueOnce({ ...PROMPT, body: "Hello {{tone}} {{name}}" });
    const onSaved = vi.fn();
    render(<InlinePromptEditor mode="edit" prompt={PROMPT} usageCount={3} onSaved={onSaved} onCancel={() => {}} />);

    expect(screen.getByText(/used by 3 workflows/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Prompt body"), { target: { value: "Hello {{tone}} {{name}}" } });
    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const arg = mutateAsync.mock.calls[0][0];
    expect(arg.id).toBe("prm_1");
    expect(arg.name).toBe("Draft");          // name preserved from loaded prompt
    expect(arg.tags).toEqual(["t"]);          // tags preserved
    expect(arg.body).toContain("{{name}}");
    expect(arg.variables.map((v: { name: string }) => v.name)).toEqual(["tone", "name"]);
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "prm_1" }));
  });

  it("revert restores the loaded body", () => {
    render(<InlinePromptEditor mode="edit" prompt={PROMPT} usageCount={1} onSaved={() => {}} onCancel={() => {}} />);
    const body = screen.getByLabelText("Prompt body") as HTMLTextAreaElement;
    fireEvent.change(body, { target: { value: "changed" } });
    expect(body.value).toBe("changed");
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    expect(body.value).toBe("Hello {{tone}}");

    const label = screen.getByLabelText("Label for tone") as HTMLInputElement;
    fireEvent.change(label, { target: { value: "Changed" } });
    expect(label.value).toBe("Changed");
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    expect(label.value).toBe("Tone");
  });
});

describe("InlinePromptEditor — create", () => {
  it("requires name + body, then POSTs without an id", async () => {
    mutateAsync.mockResolvedValueOnce({ ...PROMPT, id: "prm_new", name: "My prompt" });
    const onSaved = vi.fn();
    render(<InlinePromptEditor mode="create" usageCount={0} onSaved={onSaved} onCancel={() => {}} />);

    const create = screen.getByRole("button", { name: "Create prompt" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New prompt name"), { target: { value: "My prompt" } });
    fireEvent.change(screen.getByLabelText("Prompt body"), { target: { value: "Body {{x}}" } });
    expect(create).not.toBeDisabled();

    fireEvent.click(create);
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0][0].id).toBeUndefined();
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "prm_new" }));
  });
});
