import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { ApiActivityPanel, ApiActivityButton } from "./ApiActivityPanel";
import { logStart, logEnd, clearLog } from "../apiLog/store";

beforeEach(() => clearLog());

describe("ApiActivityPanel", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<ApiActivityPanel open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists logged calls and expands to show cURL", () => {
    const id = logStart({ kind: "rest", method: "POST", path: "/v1/containers/c_1/tasks", requestBody: { prompt: "hi" } });
    logEnd(id, { status: 201, ok: true, responseBody: { task_id: "t_1" } });

    render(<ApiActivityPanel open onClose={() => {}} />);
    expect(screen.getByText("/v1/containers/c_1/tasks")).toBeInTheDocument();

    fireEvent.click(screen.getByText("/v1/containers/c_1/tasks"));
    expect(screen.getByText(/curl -X POST/)).toBeInTheDocument();
    expect(screen.getByText(/Bearer tk_live_\*\*\*/)).toBeInTheDocument();
  });

  it("filters to errors only", () => {
    const ok = logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    logEnd(ok, { status: 200, ok: true });
    const bad = logStart({ kind: "rest", method: "GET", path: "/v1/containers" });
    logEnd(bad, { status: 500, ok: false });

    render(<ApiActivityPanel open onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Errors" }));
    expect(screen.queryByText("/v1/models")).toBeNull();
    expect(screen.getByText("/v1/containers")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<ApiActivityPanel open onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders an SSE row and a session-only tag", () => {
    const sid = logStart({ kind: "sse", method: "SSE", path: "/v1/containers/c_1/tasks/t_1/events", sse: { events: 0, closed: false } });
    logEnd(sid, { sse: { events: 3, closed: true } });
    const aid = logStart({ kind: "rest", method: "GET", path: "/v1/auth/me", sessionOnly: true });
    logEnd(aid, { status: 200, ok: true });

    render(<ApiActivityPanel open onClose={() => {}} />);
    expect(screen.getByText("SSE")).toBeInTheDocument();
    expect(screen.getByText("session")).toBeInTheDocument();
  });

  it("filters by path query", () => {
    const a = logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    logEnd(a, { status: 200, ok: true });
    const b = logStart({ kind: "rest", method: "GET", path: "/v1/containers" });
    logEnd(b, { status: 200, ok: true });

    render(<ApiActivityPanel open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Filter path…"), { target: { value: "models" } });
    expect(screen.getByText("/v1/models")).toBeInTheDocument();
    expect(screen.queryByText("/v1/containers")).toBeNull();
  });

  it("clears the log via the Clear button", () => {
    const a = logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    logEnd(a, { status: 200, ok: true });

    render(<ApiActivityPanel open onClose={() => {}} />);
    expect(screen.getByText("/v1/models")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("/v1/models")).toBeNull();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<ApiActivityPanel open onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("button shows the entry count and fires onClick", () => {
    const a = logStart({ kind: "rest", method: "GET", path: "/v1/models" });
    logEnd(a, { status: 200, ok: true });
    const onClick = vi.fn();
    render(<ApiActivityButton onClick={onClick} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "API activity" }));
    expect(onClick).toHaveBeenCalled();
  });
});
