import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/render";
import { TaskToolsField } from "./TaskToolsField";
import type { Template } from "../api/types";

const vanillaMeta = {
  driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file", "web_fetch"], tools_user_editable: true, supports_context: true },
  available_tool_specs: [
    { name: "read_file", description: "", input_schema: {}, requires_image_feature: null },
    { name: "web_fetch", description: "", input_schema: {}, requires_image_feature: "chromium" },
  ],
} as unknown as Template;

const nonEditableMeta = {
  driver_template: { driver: "claude-code", default_system_prompt: "", available_tools: [], tools_user_editable: false, supports_context: false },
  available_tool_specs: [],
} as unknown as Template;

describe("TaskToolsField", () => {
  it("renders nothing when the driver does not let tasks edit tools", () => {
    renderWithProviders(
      <TaskToolsField driverMeta={nonEditableMeta} inherited={[]} value={null} onChange={vi.fn()} />,
    );
    expect(screen.queryByLabelText("Override tools for this task")).not.toBeInTheDocument();
  });

  it("tags a tool that needs the full image variant with 'full', and leaves others untagged", async () => {
    renderWithProviders(
      <TaskToolsField driverMeta={vanillaMeta} inherited={[]} value={[]} onChange={vi.fn()} />,
    );
    const webFetch = await screen.findByLabelText("task tool web_fetch");
    expect(webFetch.closest("label")).toHaveTextContent("full");
    const readFile = screen.getByLabelText("task tool read_file");
    expect(readFile.closest("label")).not.toHaveTextContent("full");
  });

  it("toggles a tool through onChange", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <TaskToolsField driverMeta={vanillaMeta} inherited={["read_file"]} value={["read_file"]} onChange={onChange} />,
    );
    await userEvent.click(await screen.findByLabelText("task tool web_fetch"));
    expect(onChange).toHaveBeenCalledWith(["read_file", "web_fetch"]);
  });
});
