import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import ExportsEditor, { exportPathError } from "./ExportsEditor";

function renderEditor(exports: string[] = [], isLast = false, onChange = vi.fn()) {
  render(
    <ExportsEditor stepIndex={0} isLast={isLast} exports={exports} onChange={onChange} />,
  );
  return { onChange };
}

function typeDraft(value: string) {
  fireEvent.change(screen.getByLabelText("Add export path"), { target: { value } });
}

describe("exportPathError", () => {
  it("accepts relative paths and globs", () => {
    expect(exportPathError("report.pdf", [])).toBeNull();
    expect(exportPathError("dist/**", [])).toBeNull();
    expect(exportPathError("out/*.csv", [])).toBeNull();
  });

  it("rejects absolute, traversing, reserved, duplicate and oversized paths", () => {
    expect(exportPathError("/etc/passwd", [])).toMatch(/relative/i);
    expect(exportPathError("a/../b.txt", [])).toMatch(/\.\./);
    expect(exportPathError(".git/config", [])).toMatch(/can't be shared/i);
    expect(exportPathError(".agent-runtime/x", [])).toMatch(/can't be shared/i);
    expect(exportPathError("dist/**", ["dist/**"])).toMatch(/already/i);
    expect(exportPathError("x".repeat(513), [])).toMatch(/too long/i);
    expect(exportPathError("f21.txt", Array.from({ length: 20 }, (_, i) => `f${i}.txt`)))
      .toMatch(/at most 20/i);
  });
});

describe("ExportsEditor", () => {
  it("adds a trimmed path via the Add file button", () => {
    const { onChange } = renderEditor();
    typeDraft("  report.pdf  ");
    fireEvent.click(screen.getByRole("button", { name: /add file/i }));
    expect(onChange).toHaveBeenCalledWith(["report.pdf"]);
  });

  it("adds a path with Enter and clears the input", () => {
    const { onChange } = renderEditor(["a.txt"]);
    typeDraft("dist/**");
    fireEvent.keyDown(screen.getByLabelText("Add export path"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["a.txt", "dist/**"]);
    expect(screen.getByLabelText("Add export path")).toHaveValue("");
  });

  it("shows a validation error instead of adding an invalid path", () => {
    const { onChange } = renderEditor();
    typeDraft("../escape.txt");
    fireEvent.click(screen.getByRole("button", { name: /add file/i }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/\.\./);
  });

  it("clears the error once the draft changes", () => {
    renderEditor();
    typeDraft("/abs.txt");
    fireEvent.click(screen.getByRole("button", { name: /add file/i }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    typeDraft("abs.txt");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders existing paths as tags and removes one", () => {
    const { onChange } = renderEditor(["a.txt", "b.txt"]);
    expect(screen.getByText("a.txt")).toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove export 1" }));
    expect(onChange).toHaveBeenCalledWith(["b.txt"]);
  });

  it("shows the count badge only when paths exist", () => {
    renderEditor(["a.txt", "b.txt"]);
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("disables Add file while the draft is empty", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: /add file/i })).toBeDisabled();
    typeDraft("x.txt");
    expect(screen.getByRole("button", { name: /add file/i })).toBeEnabled();
  });

  it("shows the last-step note only when last with exports", () => {
    renderEditor(["a.txt"], true);
    expect(screen.getByText(/last step/i)).toBeInTheDocument();
  });

  it("hides the last-step note when not last or empty", () => {
    renderEditor(["a.txt"], false);
    expect(screen.queryByText(/last step/i)).not.toBeInTheDocument();
  });
});
