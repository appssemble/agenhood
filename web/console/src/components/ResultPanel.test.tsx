import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResultPanel } from "./ResultPanel";

const href = (p: string) => `/dl?path=${encodeURIComponent(p)}`;

// ---------------------------------------------------------------------------
// formatOutput branches (tested via rendered output)
// ---------------------------------------------------------------------------
describe("ResultPanel — output formatting", () => {
  it("pretty-prints an object as indented JSON", () => {
    render(
      <ResultPanel terminal result={{ success: true, output: { value: 42 } }} downloadHref={href} />,
    );
    // JSON.stringify({ value: 42 }, null, 2) includes  "value": 42
    expect(screen.getByText(/"value": 42/)).toBeInTheDocument();
  });

  it("renders plain string output verbatim", () => {
    render(
      <ResultPanel terminal result={{ success: true, output: "plain text" }} downloadHref={href} />,
    );
    expect(screen.getByText("plain text")).toBeInTheDocument();
  });

  it("pretty-prints nested structured output", () => {
    render(
      <ResultPanel terminal result={{ success: true, output: { items: ["a", "b"] } }} downloadHref={href} />,
    );
    expect(screen.getByText(/"items"/)).toBeInTheDocument();
  });

  it("shows the terminal empty-output copy when output is null", () => {
    render(
      <ResultPanel terminal result={{ success: false, output: null }} downloadHref={href} />,
    );
    expect(screen.getByText(/no textual output/i)).toBeInTheDocument();
  });

  it("shows the non-terminal in-progress copy when output is missing and not terminal", () => {
    render(
      <ResultPanel terminal={false} result={{ success: false, output: null }} downloadHref={href} />,
    );
    expect(screen.getByText(/Updates as the agent writes/i)).toBeInTheDocument();
  });

  it("shows empty copy when result is null", () => {
    render(
      <ResultPanel terminal result={null} downloadHref={href} />,
    );
    expect(screen.getByText(/no textual output/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// File list + per-file download hrefs
// ---------------------------------------------------------------------------
describe("ResultPanel — file list", () => {
  it("lists result files with per-file download hrefs", () => {
    render(
      <ResultPanel
        terminal
        result={{ success: true, output: "x", files: ["a/b/report.md"] }}
        downloadHref={href}
      />,
    );
    const link = screen.getByRole("link", { name: /Download a\/b\/report\.md/ });
    expect(link).toHaveAttribute("href", href("a/b/report.md"));
    // display label is the basename
    expect(link).toHaveTextContent("report.md");
  });

  it("encodes the path into the href via downloadHref", () => {
    render(
      <ResultPanel
        terminal
        result={{ success: true, output: null, files: ["some/path/out.json"] }}
        downloadHref={href}
      />,
    );
    const link = screen.getByRole("link", { name: /Download some\/path\/out\.json/ });
    expect(link).toHaveAttribute("href", "/dl?path=some%2Fpath%2Fout.json");
  });

  it("renders multiple file rows", () => {
    render(
      <ResultPanel
        terminal
        result={{ success: true, output: null, files: ["a.md", "b.md"] }}
        downloadHref={href}
      />,
    );
    expect(screen.getByRole("link", { name: /Download a\.md/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download b\.md/ })).toBeInTheDocument();
  });

  it("does not render the file section when files is empty", () => {
    render(
      <ResultPanel
        terminal
        result={{ success: true, output: "done", files: [] }}
        downloadHref={href}
      />,
    );
    expect(screen.queryByText(/Result files/i)).not.toBeInTheDocument();
  });

  it("does not render the file section when files is absent", () => {
    render(
      <ResultPanel
        terminal
        result={{ success: true, output: "done" }}
        downloadHref={href}
      />,
    );
    expect(screen.queryByText(/Result files/i)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Success/fail pill (terminal branch)
// ---------------------------------------------------------------------------
describe("ResultPanel — terminal success pill", () => {
  it("shows success pill when terminal and success=true", () => {
    render(
      <ResultPanel terminal result={{ success: true, output: "ok" }} downloadHref={href} />,
    );
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("shows failed pill when terminal and success=false", () => {
    render(
      <ResultPanel terminal result={{ success: false, output: null }} downloadHref={href} />,
    );
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("omits the pill when not terminal", () => {
    render(
      <ResultPanel terminal={false} result={{ success: true, output: "ok" }} downloadHref={href} />,
    );
    expect(screen.queryByText("success")).not.toBeInTheDocument();
  });
});
