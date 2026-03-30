import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Mcp from "./Mcp";

vi.mock("../../components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

vi.mock("../../api/queries", () => ({
  useMcpServers: () => ({
    data: { mcp_servers: [
      { id: "mcp_1", name: "linear", description: "Linear MCP", url: "https://mcp.linear.app/mcp",
        auth_type: "bearer", auth_header_name: null, secret_set: true, enabled: true,
        created_at: null, updated_at: null },
    ] },
    isLoading: false,
  }),
  useDeleteMcpServer: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("Mcp list", () => {
  it("renders the server name and host", () => {
    render(<MemoryRouter><Mcp /></MemoryRouter>);
    expect(screen.getByText("linear")).toBeInTheDocument();
    expect(screen.getByText(/mcp\.linear\.app/)).toBeInTheDocument();
  });
});
