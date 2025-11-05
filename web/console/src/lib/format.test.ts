import { describe, it, expect } from "vitest";
import { formatCompact, formatDate, shortId, relativeFromNow } from "./format";

describe("relativeFromNow", () => {
  const now = Date.parse("2026-06-29T12:00:00Z");
  it("formats past and future", () => {
    expect(relativeFromNow("2026-06-29T09:00:00Z", now)).toBe("3h ago");
    expect(relativeFromNow("2026-06-29T15:00:00Z", now)).toBe("in 3h");
    expect(relativeFromNow("2026-06-27T12:00:00Z", now)).toBe("2d ago");
    expect(relativeFromNow("2026-06-30T12:30:00Z", now)).toBe("in 1d");
    expect(relativeFromNow("2026-06-29T11:59:50Z", now)).toBe("just now");
  });
  it("handles null/unparseable", () => {
    expect(relativeFromNow(null, now)).toBe("—");
    expect(relativeFromNow("nope", now)).toBe("—");
  });
});

describe("shortId", () => {
  it("returns short ids unchanged", () => {
    expect(shortId("prm_a")).toBe("prm_a");
    expect(shortId("")).toBe("");
    expect(shortId("prm_01jyk89")).toBe("prm_01jyk89"); // 11 chars, ≤12
  });
  it("keeps the prefix and a distinguishing tail for long ids", () => {
    expect(shortId("prm_01jyk8abcdefgxyz")).toBe("prm_01j…xyz");
  });
});

describe("formatCompact", () => {
  it("millions with one decimal", () => {
    expect(formatCompact(6_000_000)).toBe("6.0M");
    expect(formatCompact(1_900_000)).toBe("1.9M");
  });
  it("thousands with one decimal", () => {
    expect(formatCompact(38_200)).toBe("38.2k");
  });
  it("small numbers unchanged", () => {
    expect(formatCompact(248)).toBe("248");
    expect(formatCompact(0)).toBe("0");
  });
});

describe("formatDate", () => {
  it("renders an em dash for empty values", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });
  it("returns unparseable input verbatim", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
  it("formats a valid ISO date with month name and year", () => {
    const out = formatDate("2026-06-14T10:00:00Z");
    expect(out).toMatch(/Jun/);
    expect(out).toMatch(/2026/);
  });
});
