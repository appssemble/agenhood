import { describe, it, expect } from "vitest";
import { toCurl, isSessionOnly } from "./curl";

const ORIGIN = "https://api.example.com";

describe("isSessionOnly", () => {
  it("flags auth, users, api-keys, credentials", () => {
    expect(isSessionOnly("/v1/auth/me")).toBe(true);
    expect(isSessionOnly("/v1/users/u_1")).toBe(true);
    expect(isSessionOnly("/v1/api-keys")).toBe(true);
    expect(isSessionOnly("/v1/credentials")).toBe(true);
  });

  it("does not flag data-plane endpoints", () => {
    expect(isSessionOnly("/v1/containers")).toBe(false);
    expect(isSessionOnly("/v1/containers/c_1/tasks")).toBe(false);
    expect(isSessionOnly("/v1/models")).toBe(false);
  });

  it("ignores query strings", () => {
    expect(isSessionOnly("/v1/containers/c_1/files?prefix=/")).toBe(false);
  });
});

describe("toCurl", () => {
  it("builds a GET without a body", () => {
    const out = toCurl({ method: "GET", path: "/v1/containers" }, ORIGIN);
    expect(out).toBe(
      `curl -X GET ${ORIGIN}/v1/containers \\\n  -H "Authorization: Bearer tk_live_***"`,
    );
  });

  it("includes a JSON body and content-type for POST", () => {
    const out = toCurl(
      { method: "POST", path: "/v1/containers/c_1/tasks", requestBody: { prompt: "hi" } },
      ORIGIN,
    );
    expect(out).toContain(`curl -X POST ${ORIGIN}/v1/containers/c_1/tasks`);
    expect(out).toContain(`-H "Content-Type: application/json"`);
    expect(out).toContain(`-d '{"prompt":"hi"}'`);
  });

  it("shell-escapes single quotes in the body", () => {
    const out = toCurl({ method: "POST", path: "/v1/containers", requestBody: { name: "O'Brien" } }, ORIGIN);
    expect(out).toContain(`'{"name":"O'\\''Brien"}'`);
  });
});
