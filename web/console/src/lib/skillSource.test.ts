import { describe, expect, it } from "vitest";
import { sourceUrlError } from "./skillSource";

describe("sourceUrlError", () => {
  it("requires https without a key", () => {
    expect(sourceUrlError("git@github.com:o/r.git", false)).toMatch(/https/);
    expect(sourceUrlError("https://github.com/o/r", false)).toBeNull();
  });
  it("requires ssh with a key", () => {
    expect(sourceUrlError("https://github.com/o/r", true)).toMatch(/ssh/i);
    expect(sourceUrlError("git@github.com:o/r.git", true)).toBeNull();
  });
  it("empty url is not an error (field just incomplete)", () => {
    expect(sourceUrlError("", true)).toBeNull();
  });
});
