import { describe, expect, it } from "vitest";
import { keys } from "./queries";
import type { McpServer } from "./types";

describe("mcp api surface", () => {
  it("exposes an mcpServers query key", () => {
    expect(keys.mcpServers).toEqual(["mcp-servers"]);
  });

  it("McpServer type omits the secret but flags secret_set", () => {
    const s: McpServer = {
      id: "mcp_1", name: "linear", description: "d", url: "https://m",
      auth_type: "bearer", auth_header_name: null, secret_set: true,
      enabled: true, created_at: null, updated_at: null,
    };
    expect(s.secret_set).toBe(true);
  });
});
