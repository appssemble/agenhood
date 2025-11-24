import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/render";
import { ActivityFeed } from "./ActivityFeed";
import type { TenantTaskSummary } from "../api/types";

const tasks: TenantTaskSummary[] = [
  { task_id: "t1", container_id: "c1", container_name: "support-bot", status: "completed",
    prompt: "do a thing", tokens_in: 30000, tokens_out: 8200, created_at: "2026-06-03T11:58:00+00:00" },
  { task_id: "t2", container_id: "c2", container_name: "qa-runner", status: "failed",
    prompt: "broke", tokens_in: 7000, tokens_out: 100, created_at: "2026-06-03T11:46:00+00:00" },
];

describe("ActivityFeed", () => {
  it("lists tasks with container name and status", () => {
    renderWithProviders(<ActivityFeed tasks={tasks} />);
    expect(screen.getByText("support-bot")).toBeInTheDocument();
    expect(screen.getByText("qa-runner")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("shows an empty message when there are no tasks", () => {
    renderWithProviders(<ActivityFeed tasks={[]} />);
    expect(screen.getByText(/no recent tasks/i)).toBeInTheDocument();
  });
});
