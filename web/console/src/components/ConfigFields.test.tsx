import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { ConfigFields } from "./ConfigFields";
import type { Template } from "../api/types";

const vanillaMeta = {
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file"], tools_user_editable: true, supports_context: true },
  available_tool_specs: [{ name: "read_file", description: "", input_schema: {}, requires_image_feature: null }],
} as unknown as Template;
const opencodeMeta = {
  driver_template: { driver: "opencode", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: false },
  available_tool_specs: [],
} as unknown as Template;

const baseValue = {
  driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "", system_prompt_mode: "augment" as const,
  tools: [] as string[], context: { variables: {}, text: null, files: [] }, skills: [] as string[], mcp_servers: [] as string[],
};

function models() {
  server.use(http.get("/v1/models", () => HttpResponse.json({ models: [
    { id: "claude-sonnet-4-6", provider: "anthropic", label: "claude-sonnet-4-6", category: "api_key", drivers: ["vanilla", "opencode"], available: true, requires: [] },
  ] })));
}

describe("ConfigFields", () => {
  it("shows the tool picker for a vanilla driver", async () => {
    models();
    renderWithProviders(<ConfigFields value={baseValue} driverMeta={vanillaMeta} enabledSkills={[]} enabledMcpServers={[]} onPatch={vi.fn()} />);
    expect(await screen.findByLabelText("read_file")).toBeInTheDocument();
  });

  it("toggles a tool through onPatch", async () => {
    models();
    const onPatch = vi.fn();
    renderWithProviders(<ConfigFields value={baseValue} driverMeta={vanillaMeta} enabledSkills={[]} enabledMcpServers={[]} onPatch={onPatch} />);
    await userEvent.click(await screen.findByLabelText("read_file"));
    expect(onPatch).toHaveBeenCalledWith({ tools: ["read_file"] });
  });

  it("renders titled section cards", async () => {
    models();
    renderWithProviders(<ConfigFields value={baseValue} driverMeta={vanillaMeta} enabledSkills={[]} enabledMcpServers={[]} onPatch={vi.fn()} />);
    expect(await screen.findByText("Model")).toBeInTheDocument();
    expect(screen.getByText("System prompt")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("Standing context")).toBeInTheDocument();
    // the prompt-mode control lives in the System prompt card header
    expect(screen.getByText("Augment")).toBeInTheDocument();
  });

  it("hides tools/context and shows skills for opencode", async () => {
    models();
    const oc = { ...baseValue, driver: "opencode" };
    renderWithProviders(<ConfigFields value={oc} driverMeta={opencodeMeta} enabledSkills={[{ id: "skl_1", name: "git-release", description: "", enabled: true, source_type: "inline", created_at: null, updated_at: null }]} enabledMcpServers={[]} onPatch={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/manages its own tools and context/i)).toBeInTheDocument());
    expect(screen.queryByLabelText("read_file")).not.toBeInTheDocument();
    expect(screen.getByLabelText("git-release")).toBeInTheDocument();
  });

  it("toggles an MCP server into config.mcp_servers", async () => {
    models();
    const onPatch = vi.fn();
    const oc = { ...baseValue, driver: "opencode" };
    renderWithProviders(
      <ConfigFields
        value={oc}
        driverMeta={opencodeMeta}
        enabledSkills={[]}
        enabledMcpServers={[{ id: "mcp_1", name: "linear", description: "Linear MCP", url: "https://m", auth_type: "bearer" as const, auth_header_name: null, secret_set: true, enabled: true, created_at: null, updated_at: null }]}
        onPatch={onPatch}
      />,
    );
    await userEvent.click(screen.getByLabelText("linear"));
    expect(onPatch).toHaveBeenCalledWith({ mcp_servers: ["mcp_1"] });
  });
});
