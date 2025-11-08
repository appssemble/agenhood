// web/console/src/api/skills-queries.test.ts
import { describe, it, expect } from "vitest";
import { keys } from "./queries";

describe("skills query keys", () => {
  it("exposes a skills key", () => {
    expect(keys.skills).toEqual(["skills"]);
  });
});
