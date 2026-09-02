import { describe, it, expect, vi } from "vitest";
import { screen, act } from "@testing-library/react";
import { renderWithProviders } from "../test/render";
import { ActivityFeed } from "./ActivityFeed";
import type { TenantTaskSummary } from "../api/types";

const tasks: TenantTaskSummary[] = [
  { task_id: "t1", container_id: "c1", container_name: "support-bot", status: "completed",
    prompt: "do a thing", tokens_in: 30000, tokens_out: 8200, created_at: "2026-06-03T11:58:00+00:00",
    started_at: "2026-06-03T11:58:00+00:00", ended_at: "2026-06-03T11:58:42+00:00" },
  { task_id: "t2", container_id: "c2", container_name: "qa-runner", status: "failed",
    prompt: "broke", tokens_in: 7000, tokens_out: 100, created_at: "2026-06-03T11:46:00+00:00",
    started_at: "2026-06-03T11:46:00+00:00", ended_at: "2026-06-03T11:48:13+00:00" },
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

describe("ActivityFeed durations", () => {
  it("shows how long each finished task took", () => {
    renderWithProviders(<ActivityFeed tasks={tasks} />);
    expect(screen.getByText("42.0s")).toBeInTheDocument();
    expect(screen.getByText("2m 13s")).toBeInTheDocument();
  });

  it("shows a dash for a task that never started", () => {
    const pending: TenantTaskSummary[] = [
      { task_id: "t3", container_id: "c3", container_name: "queued", status: "pending",
        prompt: "waiting", tokens_in: 0, tokens_out: 0, created_at: "2026-06-03T12:00:00+00:00",
        started_at: null, ended_at: null },
    ];
    renderWithProviders(<ActivityFeed tasks={pending} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("counts up while a task is still running", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-03T12:00:10Z"));
    const running: TenantTaskSummary[] = [
      { task_id: "t4", container_id: "c4", container_name: "live", status: "running",
        prompt: "going", tokens_in: 10, tokens_out: 0, created_at: "2026-06-03T12:00:00+00:00",
        started_at: "2026-06-03T12:00:00+00:00", ended_at: null },
    ];
    renderWithProviders(<ActivityFeed tasks={running} />);
    expect(screen.getByText("10.0s")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText("15.0s")).toBeInTheDocument();
    vi.useRealTimers();
  });
});
