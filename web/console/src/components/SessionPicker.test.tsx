import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { SessionPicker } from "./SessionPicker";

describe("SessionPicker", () => {
  it("shows 'No session' selected by default and lists existing sessions", async () => {
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({
      sessions: [{ session_id: "sess-1", driver: "vanilla", task_count: 3,
        first_created_at: "t1", last_created_at: "t2", busy: false }],
    })));
    renderWithProviders(<SessionPicker cid="con_1" sessionId={null} onChange={() => {}} />);
    expect(await screen.findByText(/no session/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /no session/i }));
    expect(await screen.findByText(/sess-1/)).toBeInTheDocument();
  });

  it("calls onChange with a fresh id when 'New session' is picked", async () => {
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({ sessions: [] })));
    let picked: string | null = null;
    renderWithProviders(
      <SessionPicker cid="con_1" sessionId={null} onChange={(id) => { picked = id; }} />
    );
    await userEvent.click(await screen.findByRole("button", { name: /no session/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /new session/i }));
    await waitFor(() => expect(picked).toBeTruthy());
  });

  it("calls onChange with an existing session's id when picked from the list", async () => {
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({
      sessions: [{ session_id: "sess-1", driver: "vanilla", task_count: 3,
        first_created_at: "t1", last_created_at: "t2", busy: false }],
    })));
    let picked: string | null = null;
    renderWithProviders(
      <SessionPicker cid="con_1" sessionId={null} onChange={(id) => { picked = id; }} />
    );
    await userEvent.click(await screen.findByRole("button", { name: /no session/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /sess-1/ }));
    expect(picked).toBe("sess-1");
  });
});
