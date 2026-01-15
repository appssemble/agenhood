import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import Skills from "./Skills";

// The list endpoint returns the summary shape (no body).
const SKILLS = [
  { id: "skl_1", name: "git-release", description: "Make releases", enabled: true, source_type: "inline", created_at: null, updated_at: null },
];

describe("Skills settings page (list)", () => {
  it("lists the tenant's skills", async () => {
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: SKILLS })));
    renderWithProviders(<Skills />);
    await waitFor(() => expect(screen.getByText("git-release")).toBeInTheDocument());
    expect(screen.getByText("Make releases")).toBeInTheDocument();
  });

  it("links the New skill action to the editor route", async () => {
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: SKILLS })));
    renderWithProviders(<Skills />);
    const link = await screen.findByRole("link", { name: /new skill/i });
    expect(link).toHaveAttribute("href", "/settings/skills/new");
  });

  it("links each row's Edit action to the edit route", async () => {
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: SKILLS })));
    renderWithProviders(<Skills />);
    const edit = await screen.findByRole("link", { name: /^Edit$/ });
    expect(edit).toHaveAttribute("href", "/settings/skills/skl_1/edit");
  });

  it("offers an install-from-git path from the empty state", async () => {
    server.use(http.get("/v1/skills", () => HttpResponse.json({ skills: [] })));
    renderWithProviders(<Skills />);
    const git = await screen.findByRole("link", { name: /install from git/i });
    expect(git).toHaveAttribute("href", "/settings/skills/new?source=git");
  });
});
