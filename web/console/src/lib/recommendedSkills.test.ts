import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import {
  fetchRecommendedSkills,
  groupByCategory,
  type RecommendedRepo,
} from "./recommendedSkills";

const CATALOG =
  "https://raw.githubusercontent.com/appssemble/awesome-skill-md/main/skills.json";

// ---------------------------------------------------------------------------
// fetchRecommendedSkills
// ---------------------------------------------------------------------------

describe("fetchRecommendedSkills", () => {
  it("expands skillFiles into per-subpath skills and drops entries with none", async () => {
    server.use(
      http.get(CATALOG, () =>
        HttpResponse.json({
          skills: [
            {
              name: "Acme",
              url: "https://github.com/acme/repo",
              category: "Research",
              description: "d",
              // duplicate "a/SKILL.md" → deduped to one "a" subpath
              skillFiles: ["a/SKILL.md", "a/SKILL.md", "b/c/SKILL.md"],
            },
            // no skillFiles property → dropped (covers the ternary `else []` branch)
            { name: "NoFiles", url: "https://github.com/x/y" },
          ],
        }),
      ),
    );
    const repos = await fetchRecommendedSkills();

    expect(repos).toHaveLength(1);
    expect(repos[0].skills.map((s) => s.subpath)).toEqual(["a", "b/c"]);
    expect(repos[0].skills[0].id).toBe("https://github.com/acme/repo#a");
    expect(repos[0].branch).toBe("main"); // default when branch is absent
  });

  it("uses a custom branch when the catalog entry provides one", async () => {
    server.use(
      http.get(CATALOG, () =>
        HttpResponse.json({
          skills: [
            {
              name: "Branched",
              url: "https://github.com/org/branched",
              branch: "v2",
              skillFiles: ["SKILL.md"],
            },
          ],
        }),
      ),
    );
    const repos = await fetchRecommendedSkills();
    expect(repos[0].branch).toBe("v2");
  });

  it("defaults category to 'Other' when missing or empty", async () => {
    server.use(
      http.get(CATALOG, () =>
        HttpResponse.json({
          skills: [
            // no category field
            {
              name: "NoCat",
              url: "https://github.com/org/nocat",
              skillFiles: ["SKILL.md"],
            },
            // empty string category
            {
              name: "EmptyCat",
              url: "https://github.com/org/emptycat",
              category: "",
              skillFiles: ["SKILL.md"],
            },
          ],
        }),
      ),
    );
    const repos = await fetchRecommendedSkills();
    expect(repos[0].category).toBe("Other");
    expect(repos[1].category).toBe("Other");
  });

  it("handles a root-level SKILL.md (empty subpath)", async () => {
    server.use(
      http.get(CATALOG, () =>
        HttpResponse.json({
          skills: [
            {
              name: "RootSkill",
              url: "https://github.com/org/root",
              skillFiles: ["SKILL.md"],
            },
          ],
        }),
      ),
    );
    const repos = await fetchRecommendedSkills();
    expect(repos[0].skills[0].subpath).toBe("");
    // id ends with "#" for root-level
    expect(repos[0].skills[0].id).toBe("https://github.com/org/root#");
  });

  it("skips malformed entries missing url or name", async () => {
    server.use(
      http.get(CATALOG, () =>
        HttpResponse.json({
          skills: [
            // missing url → skipped
            { name: "NoUrl", skillFiles: ["SKILL.md"] },
            // missing name → skipped
            { url: "https://github.com/org/noname", skillFiles: ["SKILL.md"] },
            // valid entry
            {
              name: "Valid",
              url: "https://github.com/org/valid",
              skillFiles: ["SKILL.md"],
            },
          ],
        }),
      ),
    );
    const repos = await fetchRecommendedSkills();
    expect(repos).toHaveLength(1);
    expect(repos[0].repoName).toBe("Valid");
  });

  it("throws on a non-ok response", async () => {
    server.use(
      http.get(CATALOG, () => new HttpResponse(null, { status: 500 })),
    );
    await expect(fetchRecommendedSkills()).rejects.toThrow(/HTTP 500/);
  });

  it("throws when catalog format is unexpected (skills not an array)", async () => {
    server.use(
      http.get(CATALOG, () => HttpResponse.json({ skills: "oops" })),
    );
    await expect(fetchRecommendedSkills()).rejects.toThrow(
      /unexpected catalog format/,
    );
  });
});

// ---------------------------------------------------------------------------
// groupByCategory
// ---------------------------------------------------------------------------

describe("groupByCategory", () => {
  function repo(id: string, category: string): RecommendedRepo {
    return { id, repoName: id, url: id, category, description: "", branch: "main", skills: [] };
  }

  it("groups by category preserving first-seen order", () => {
    const groups = groupByCategory([repo("a", "Z"), repo("b", "A"), repo("c", "Z")]);
    expect(groups.map((g) => g.category)).toEqual(["Z", "A"]);
    // "c" appended to the existing "Z" group (covers the `list.push(repo)` branch)
    expect(groups[0].items.map((r) => r.id)).toEqual(["a", "c"]);
    expect(groups[1].items.map((r) => r.id)).toEqual(["b"]);
  });

  it("returns an empty array for an empty input", () => {
    expect(groupByCategory([])).toEqual([]);
  });

  it("returns a single group when all repos share a category", () => {
    const groups = groupByCategory([repo("a", "X"), repo("b", "X"), repo("c", "X")]);
    expect(groups).toHaveLength(1);
    expect(groups[0].items.map((r) => r.id)).toEqual(["a", "b", "c"]);
  });
});
