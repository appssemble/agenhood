import { freshness } from "./freshness";

test("buckets last-used into recent/stale/never", () => {
  const now = new Date("2026-06-02T00:00:00Z");
  expect(freshness(null, now).bucket).toBe("never");
  expect(freshness("2026-06-01T23:00:00Z", now).bucket).toBe("recent");
  expect(freshness("2026-03-01T00:00:00Z", now).bucket).toBe("stale");
});
