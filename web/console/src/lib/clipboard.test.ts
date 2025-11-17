import { describe, it, expect, vi, afterEach } from "vitest";
import { copyText } from "./clipboard";

describe("copyText", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses navigator.clipboard.writeText when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const ok = await copyText("prm_abc");
    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith("prm_abc");
  });

  it("falls back to execCommand when the clipboard API is missing", async () => {
    vi.stubGlobal("navigator", {});
    const exec = vi.fn().mockReturnValue(true);
    document.execCommand = exec as unknown as typeof document.execCommand;
    const ok = await copyText("prm_xyz");
    expect(ok).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });
});
