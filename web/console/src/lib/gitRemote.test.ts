import { describe, it, expect } from "vitest";
import { validateSshUrl, validateBranch } from "./gitRemote";

describe("validateSshUrl", () => {
  it("accepts scp + ssh forms", () => {
    expect(validateSshUrl("git@github.com:a/b.git")).toBeNull();
    expect(validateSshUrl("ssh://git@gitlab.com:22/g/r.git")).toBeNull();
  });
  it("rejects https / no path / empty", () => {
    expect(validateSshUrl("https://github.com/a/b.git")).toMatch(/ssh/i);
    expect(validateSshUrl("git@github.com:")).toMatch(/path/i);
    expect(validateSshUrl("")).toBeTruthy();
  });
  it("rejects shell metacharacters in host", () => {
    expect(validateSshUrl("git@a;curl|sh:r/x")).toBeTruthy();
    expect(validateSshUrl("git@h$(id):r/x")).toBeTruthy();
  });
});

describe("validateBranch", () => {
  it("accepts valid", () => {
    expect(validateBranch("feature/x")).toBeNull();
    expect(validateBranch("main")).toBeNull();
  });
  it("rejects invalid", () => {
    expect(validateBranch("a..b")).toBeTruthy();
    expect(validateBranch("bad name")).toBeTruthy();
    expect(validateBranch("")).toBeTruthy();
  });
});
