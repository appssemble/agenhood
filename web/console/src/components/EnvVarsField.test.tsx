import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EnvVarsField } from "./EnvVarsField";
import type { EnvVar } from "../api/types";

describe("EnvVarsField", () => {
  it("adds a row", () => {
    const onChange = vi.fn();
    render(<EnvVarsField value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByText("+ Add variable"));
    expect(onChange).toHaveBeenCalledWith([{ name: "", value: "", secret: false }]);
  });

  it("edits name uppercased and value", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "", value: "", secret: false }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Env name 1"), { target: { value: "my_var" } });
    expect(onChange).toHaveBeenCalledWith([{ name: "MY_VAR", value: "", secret: false }]);
  });

  it("masks a saved secret and offers Replace", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "KEY", value: null, secret: true }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    expect(screen.queryByLabelText("Env value 1")).toBeNull();
    fireEvent.click(screen.getByText("Replace"));
    expect(onChange).toHaveBeenCalledWith([{ name: "KEY", value: "", secret: true }]);
  });

  it("removes a row", () => {
    const onChange = vi.fn();
    const rows: EnvVar[] = [{ name: "A", value: "1", secret: false }];
    render(<EnvVarsField value={rows} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Remove env var 1"));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
