import { describe, it, expect } from "vitest";
import { driverLabel, driverDesc, driverIcon } from "./drivers";
import { Icons } from "../ui/Icon";

describe("drivers", () => {
  it("maps vanilla to the barebones label, passes others through", () => {
    expect(driverLabel("vanilla")).toBe("barebones");
    expect(driverLabel("codex")).toBe("codex");
  });

  it("gives each known driver a description and falls back for unknown", () => {
    expect(driverDesc("opencode")).toMatch(/manages its own tools/i);
    expect(driverDesc("mystery")).toBe("Configurable agent driver.");
  });

  it("maps known drivers to their icon, unknown to Star", () => {
    expect(driverIcon("vanilla")).toBe(Icons.Cube);
    expect(driverIcon("opencode")).toBe(Icons.Code);
    expect(driverIcon("codex")).toBe(Icons.Bot);
    expect(driverIcon("mystery")).toBe(Icons.Star);
  });
});
