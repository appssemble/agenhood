import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EnvVarsField } from "./EnvVarsField";
import type { EnvVar } from "../api/types";

describe("EnvVarsField", () => {
  it("shows an empty state and adds a row", () => {
    const onChange = vi.fn();
    render(<EnvVarsField value={[]} onChange={onChange} />);
    expect(screen.getByText("No environment variables yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /add variable/i }));
    expect(onChange).toHaveBeenCalledWith([{ name: "", value: "", secret: false }]);
  });

  it("edits name uppercased and value", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "", value: "", secret: false }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Env name 1"), { target: { value: "my_var" } });
    expect(onChange).toHaveBeenCalledWith([{ name: "MY_VAR", value: "", secret: false }]);
  });

  it("masks a saved secret, locks its name, and offers Replace", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "KEY", value: null, secret: true }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    // No editable value input; the name is read-only (keep-semantics match by name).
    expect(screen.queryByLabelText("Env value 1")).toBeNull();
    expect(screen.getByLabelText("Env name 1")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Secret 1")).toBeDisabled();
    fireEvent.click(screen.getByText("Replace"));
    expect(onChange).toHaveBeenCalledWith([{ name: "KEY", value: "", secret: true }]);
  });

  it("types secrets masked with a reveal toggle", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "KEY", value: "s3", secret: true }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    const input = screen.getByLabelText("Env value 1");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show secret value 1" }));
    expect(input).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Hide secret value 1" }));
    expect(input).toHaveAttribute("type", "password");
  });

  it("never shows stale plaintext after a row flips to saved-secret", () => {
    // Simulates save: the editable secret (typed plaintext) is replaced by the
    // masked server response. The reused input must not keep the old text.
    const onChange = vi.fn();
    const { rerender } = render(
      <EnvVarsField value={[{ name: "KEY", value: "s3cret-plain", secret: true }]} onChange={onChange} />,
    );
    rerender(<EnvVarsField value={[{ name: "KEY", value: null, secret: true }]} onChange={onChange} />);
    expect(screen.queryByDisplayValue("s3cret-plain")).toBeNull();
  });

  it("removes a row", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "A", value: "1", secret: false }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Remove env var 1"));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
