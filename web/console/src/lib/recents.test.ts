import { describe, it, expect } from "vitest";
import { sortByRecency } from "./recents";
import type { Container } from "../api/types";

function con(id: string, last: string | null): Container {
  return {
    id,
    name: id,
    external_id: null,
    status: "running",
    image_variant: "slim",
    image_tag: "t",
    config: { driver: "vanilla", model: "m" } as Container["config"],
    metadata: {},
    last_task_at: last,
    created_at: "2026-01-01T00:00:00Z",
    error_message: null,
  };
}

describe("sortByRecency", () => {
  it("orders most-recent first and sinks null last_task_at", () => {
    const out = sortByRecency([
      con("a", "2026-06-01T00:00:00Z"),
      con("b", null),
      con("c", "2026-06-20T00:00:00Z"),
    ]);
    expect(out.map((c) => c.id)).toEqual(["c", "a", "b"]);
  });

  it("does not mutate the input array", () => {
    const input = [
      con("a", "2026-06-01T00:00:00Z"),
      con("c", "2026-06-20T00:00:00Z"),
    ];
    sortByRecency(input);
    expect(input.map((c) => c.id)).toEqual(["a", "c"]);
  });

  it("two nulls preserve relative order (both sink equally)", () => {
    const out = sortByRecency([
      con("a", null),
      con("b", "2026-06-10T00:00:00Z"),
      con("c", null),
    ]);
    expect(out[0].id).toBe("b");
    // a and c are both null, so they appear after b in some stable order
    expect(out.slice(1).map((x) => x.id).sort()).toEqual(["a", "c"]);
  });

  it("returns a single-element array unchanged", () => {
    const input = [con("x", "2026-06-01T00:00:00Z")];
    expect(sortByRecency(input).map((c) => c.id)).toEqual(["x"]);
  });
});
