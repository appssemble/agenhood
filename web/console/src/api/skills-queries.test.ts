// web/console/src/api/skills-queries.test.ts
import { describe, it, expect } from "vitest";
import { keys } from "./queries";
import { useSkillGitDiscover } from "./queries";
import type { DiscoveredSkill, SkillGitDiscoverResponse } from "./queries";

describe("skills query keys", () => {
  it("exposes a skills key", () => {
    expect(keys.skills).toEqual(["skills"]);
  });
});

describe("git discover", () => {
  it("exposes the discover mutation hook", () => {
    // Runtime import: fails before the hook exists (type-only imports are
    // erased by esbuild and would pass vacuously).
    expect(typeof useSkillGitDiscover).toBe("function");
  });

  it("models the discover response", () => {
    const skill: DiscoveredSkill = {
      subpath: "plugins/x", name: "x", description: "d",
      valid: true, error: null, installed: false,
    };
    const res: SkillGitDiscoverResponse = {
      ok: true, pinned_sha: "a".repeat(40), truncated: false, skills: [skill],
    };
    expect(res.skills[0].subpath).toBe("plugins/x");
  });
});
