import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import McpEditor from "./McpEditor";

vi.mock("../../api/queries", () => ({
  useSaveMcpServer: () => ({ mutateAsync: vi.fn(), isPending: false }),
  fetchMcpServer: vi.fn(),
}));

vi.mock("../../components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

describe("McpEditor (create mode)", () => {
  it("shows the url field and hides the header-name field until auth_type=header", () => {
    render(<MemoryRouter><McpEditor /></MemoryRouter>);
    expect(screen.getByLabelText(/url/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/header name/i)).not.toBeInTheDocument();
  });
});
