import { describe, it, expect } from "vitest";
import { redact } from "./redact";

describe("redact", () => {
  it("masks sensitive fields case-insensitively", () => {
    expect(redact({ name: "x", password: "p", API_KEY: "k" })).toEqual({
      name: "x",
      password: "***",
      API_KEY: "***",
    });
  });

  it("recurses into nested objects and arrays", () => {
    const input = { items: [{ token: "t", label: "ok" }], nested: { secret: "s" } };
    expect(redact(input)).toEqual({
      items: [{ token: "***", label: "ok" }],
      nested: { secret: "***" },
    });
  });

  it("leaves primitives and non-sensitive data untouched", () => {
    expect(redact("hello")).toBe("hello");
    expect(redact(42)).toBe(42);
    expect(redact({ a: 1, b: [2, 3] })).toEqual({ a: 1, b: [2, 3] });
  });

  it("masks the OAuth/credential token family", () => {
    expect(redact({ access_token: "a", refresh_token: "b", id_token: "c", client_secret: "d" })).toEqual({
      access_token: "***",
      refresh_token: "***",
      id_token: "***",
      client_secret: "***",
    });
  });

  it("scrubs issued API keys by value, anywhere", () => {
    expect(redact("tk_test_zzz999")).toBe("tk_test_***");
    expect(redact({ note: "your key is tk_live_ABCDEF123456 — keep it safe" })).toEqual({
      note: "your key is tk_live_*** — keep it safe",
    });
  });

  it("scrubs bearer tokens in string values", () => {
    expect(redact({ h: "Bearer abc.def-ghi" })).toEqual({ h: "Bearer ***" });
  });

  it("does NOT over-redact intentionally-safe tail/prefix fields", () => {
    const safe = { last4: "4242", token_last4: "ab12", prefix: "tk_live_", account_tail: "x9z1" };
    expect(redact(safe)).toEqual(safe);
  });
});
