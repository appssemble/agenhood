import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EventFeed } from "./EventFeed";
import type { Event } from "../api/types";

describe("EventFeed codex events", () => {
  it("renders codex_stdout and codex_event rows", () => {
    const events: Event[] = [
      { seq: 1, type: "codex_stdout", ts: "2026-06-08T00:00:00Z", payload: { line: "hello" } },
      { seq: 2, type: "codex_event", ts: "2026-06-08T00:00:01Z", payload: { raw: { type: "turn.completed" } } },
    ] as unknown as Event[];
    render(<EventFeed events={events} cid="c1" />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText(/turn\.completed/)).toBeInTheDocument();
  });
});

describe("EventFeed durations", () => {
  it("shows each row's gap to the next event", () => {
    const events: Event[] = [
      { seq: 1, type: "log", ts: "2026-09-02T10:00:00Z", payload: { level: "info", message: "first" } },
      { seq: 2, type: "log", ts: "2026-09-02T10:00:02Z", payload: { level: "info", message: "second" } },
    ] as unknown as Event[];
    render(<EventFeed events={events} cid="c1" endMs={Date.parse("2026-09-02T10:00:05Z")} />);
    expect(screen.getByText("2.0s")).toBeInTheDocument();
    expect(screen.getByText("3.0s")).toBeInTheDocument();
  });

  it("measures the last row against endMs", () => {
    const events: Event[] = [
      { seq: 1, type: "log", ts: "2026-09-02T10:00:00Z", payload: { level: "info", message: "only" } },
    ] as unknown as Event[];
    render(<EventFeed events={events} cid="c1" endMs={Date.parse("2026-09-02T10:00:07Z")} />);
    expect(screen.getByText("7.0s")).toBeInTheDocument();
  });
});
