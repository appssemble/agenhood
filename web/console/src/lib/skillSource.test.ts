import { describe, expect, it } from "vitest";
import { normalizeSourceUrl, sourceUrlError } from "./skillSource";

describe("normalizeSourceUrl", () => {
  it("converts https to scp-ssh when a key is attached", () => {
    expect(normalizeSourceUrl("https://github.com/org/repo", true)).toBe("git@github.com:org/repo.git");
    expect(normalizeSourceUrl("https://github.com/org/repo.git", true)).toBe("git@github.com:org/repo.git");
    expect(normalizeSourceUrl("https://github.com/org/repo/", true)).toBe("git@github.com:org/repo.git");
    expect(normalizeSourceUrl("https://gitlab.example.com/team/sub/repo", true)).toBe("git@gitlab.example.com:team/sub/repo.git");
  });
  it("converts ssh forms to https when no key is attached", () => {
    expect(normalizeSourceUrl("git@github.com:org/repo.git", false)).toBe("https://github.com/org/repo");
    expect(normalizeSourceUrl("git@github.com:org/repo", false)).toBe("https://github.com/org/repo");
    expect(normalizeSourceUrl("ssh://git@github.com/org/repo.git", false)).toBe("https://github.com/org/repo");
  });
  it("leaves already-correct forms unchanged", () => {
    expect(normalizeSourceUrl("git@github.com:org/repo.git", true)).toBe("git@github.com:org/repo.git");
    expect(normalizeSourceUrl("https://github.com/org/repo", false)).toBe("https://github.com/org/repo");
  });
  it("returns unparseable input unchanged (validation reports it)", () => {
    expect(normalizeSourceUrl("not a url", true)).toBe("not a url");
    expect(normalizeSourceUrl("ftp://github.com/x/y", false)).toBe("ftp://github.com/x/y");
    expect(normalizeSourceUrl("", true)).toBe("");
  });
});

describe("sourceUrlError (on normalized values)", () => {
  it("accepts both pasted forms once normalized", () => {
    expect(sourceUrlError(normalizeSourceUrl("git@github.com:o/r.git", false), false)).toBeNull();
    expect(sourceUrlError(normalizeSourceUrl("https://github.com/o/r", true), true)).toBeNull();
  });
  it("still rejects urls that can't be normalized", () => {
    expect(sourceUrlError(normalizeSourceUrl("http://github.com/o/r", false), false)).toMatch(/repository URL/);
    expect(sourceUrlError(normalizeSourceUrl("not a url", true), true)).toMatch(/repository URL/);
  });
  it("empty url is not an error (field just incomplete)", () => {
    expect(sourceUrlError("", true)).toBeNull();
  });
});
