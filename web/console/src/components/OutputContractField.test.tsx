import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { parseSchema, OutputContractField } from "./OutputContractField";

// ---------------------------------------------------------------------------
// Pure function: parseSchema
// ---------------------------------------------------------------------------
describe("parseSchema", () => {
  it("empty string is valid with no value", () => {
    expect(parseSchema("   ")).toEqual({ ok: true, value: undefined });
  });

  it("empty string (zero-length) is valid with no value", () => {
    expect(parseSchema("")).toEqual({ ok: true, value: undefined });
  });

  it("rejects a JSON array", () => {
    expect(parseSchema("[1,2]").ok).toBe(false);
  });

  it("rejects a bare number", () => {
    expect(parseSchema("42").ok).toBe(false);
  });

  it("rejects a bare null", () => {
    expect(parseSchema("null").ok).toBe(false);
  });

  it("rejects a bare string value", () => {
    expect(parseSchema('"hello"').ok).toBe(false);
  });

  it("rejects malformed JSON", () => {
    const r = parseSchema("{not json");
    expect(r.ok).toBe(false);
    expect((r as { ok: false; error: string }).error).toBeTruthy();
  });

  it("accepts a valid JSON object", () => {
    expect(parseSchema('{"type":"object"}')).toEqual({ ok: true, value: { type: "object" } });
  });

  it("accepts a nested JSON object and preserves structure", () => {
    const result = parseSchema('{"type":"object","properties":{"x":{"type":"string"}}}');
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toHaveProperty("type", "object");
      expect(result.value).toHaveProperty("properties");
    }
  });

  it("accepts an empty object {}", () => {
    const result = parseSchema("{}");
    expect(result).toEqual({ ok: true, value: {} });
  });
});

// Shared no-op for props that aren't under test
const noop = () => {};

// ---------------------------------------------------------------------------
// Component: structured-output gating
// ---------------------------------------------------------------------------
describe("OutputContractField structured gating", () => {

  it("disables the Structured button when structuredSupported=false", () => {
    render(
      <OutputContractField
        type="text"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={false}
        driver="opencode"
      />,
    );
    expect(screen.getByRole("button", { name: /Structured/ })).toBeDisabled();
  });

  it("shows the driver note when structuredSupported=false", () => {
    render(
      <OutputContractField
        type="text"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={false}
        driver="opencode"
      />,
    );
    // Note component renders with role="note"; driver name should appear inside it
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/opencode/);
  });

  it("enables the Structured button when structuredSupported=true", () => {
    render(
      <OutputContractField
        type="text"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    expect(screen.getByRole("button", { name: /Structured/ })).toBeEnabled();
  });

  it("does not render the driver note when structuredSupported=true", () => {
    render(
      <OutputContractField
        type="text"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows the schema textarea when type=structured", () => {
    render(
      <OutputContractField
        type="structured"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    expect(screen.getByRole("textbox", { name: /Response schema/i })).toBeInTheDocument();
  });

  it("does not show the schema textarea when type=text", () => {
    render(
      <OutputContractField
        type="text"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    expect(screen.queryByRole("textbox", { name: /Response schema/i })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Event handler coverage — invoke onClick/onChange arrow functions
// ---------------------------------------------------------------------------
describe("OutputContractField event handlers", () => {
  it("calls onTypeChange with the clicked type value", async () => {
    const onTypeChange = vi.fn();
    render(
      <OutputContractField
        type="text"
        onTypeChange={onTypeChange}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Files/ }));
    expect(onTypeChange).toHaveBeenCalledWith("files");
  });

  it("clicking Text button calls onTypeChange with 'text'", async () => {
    const onTypeChange = vi.fn();
    render(
      <OutputContractField
        type="structured"
        onTypeChange={onTypeChange}
        schemaText=""
        onSchemaTextChange={noop}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Text/ }));
    expect(onTypeChange).toHaveBeenCalledWith("text");
  });

  it("Insert example button calls onSchemaTextChange with the example JSON", async () => {
    const onSchemaTextChange = vi.fn();
    render(
      <OutputContractField
        type="structured"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={onSchemaTextChange}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Insert example/i }));
    expect(onSchemaTextChange).toHaveBeenCalled();
    const arg = onSchemaTextChange.mock.calls[0][0] as string;
    expect(arg).toContain('"type": "object"');
  });

  it("Clear button calls onSchemaTextChange with empty string", async () => {
    const onSchemaTextChange = vi.fn();
    render(
      <OutputContractField
        type="structured"
        onTypeChange={noop}
        schemaText='{"type":"object"}'
        onSchemaTextChange={onSchemaTextChange}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Clear/i }));
    expect(onSchemaTextChange).toHaveBeenCalledWith("");
  });

  it("typing in the schema textarea calls onSchemaTextChange with the new text", async () => {
    const onSchemaTextChange = vi.fn();
    render(
      <OutputContractField
        type="structured"
        onTypeChange={noop}
        schemaText=""
        onSchemaTextChange={onSchemaTextChange}
        structuredSupported={true}
        driver="vanilla"
      />,
    );
    const textarea = screen.getByRole("textbox", { name: /Response schema/i });
    await userEvent.type(textarea, "{{");
    expect(onSchemaTextChange).toHaveBeenCalled();
  });
});
