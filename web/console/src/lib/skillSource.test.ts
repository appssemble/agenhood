import { describe, it, expect } from "vitest";
import { urlError } from "./skillSource";

describe("urlError", () => {
  it("accepts a valid https git url (null = no error)", () => {
    expect(urlError("https://github.com/x/y.git")).toBeNull();
  });

  it("accepts any https:// url with a path", () => {
    expect(urlError("https://gitlab.com/org/repo")).toBeNull();
  });

  it("treats empty string as not-yet-an-error", () => {
    expect(urlError("")).toBeNull();
  });

  it("rejects http:// url", () => {
    expect(urlError("http://github.com/x/y")).toMatch(/https/);
  });

  it("rejects bare domain (no scheme)", () => {
    expect(urlError("github.com/x/y")).toMatch(/https/);
  });

  it("rejects ssh/git@ url", () => {
    expect(urlError("git@github.com:org/repo.git")).toMatch(/https/);
  });

  it("rejects ftp:// url", () => {
    expect(urlError("ftp://github.com/x/y")).toMatch(/https/);
  });
});
