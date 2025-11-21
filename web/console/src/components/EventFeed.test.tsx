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
