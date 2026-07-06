import { describe, it, expect } from "vitest";
import { newSessionId } from "./sessions";

describe("newSessionId", () => {
  it("returns a non-empty unique string on each call", () => {
    const a = newSessionId();
    const b = newSessionId();
    expect(a).toBeTruthy();
    expect(b).toBeTruthy();
    expect(a).not.toBe(b);
  });
});
