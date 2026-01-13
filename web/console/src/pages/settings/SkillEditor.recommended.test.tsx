import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import SkillEditor from "./SkillEditor";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({}), // create mode
  useNavigate: () => navigate,
}));

const CATALOG_URL =
  "https://raw.githubusercontent.com/appssemble/awesome-skill-md/main/skills.json";

const catalog = {
  title: "Awesome SKILL.md",
  count: 2,
  skills: [
    {
      name: "acme/pdf", owner: "acme", repo: "pdf",
      url: "https://github.com/acme/pdf",
      category: "Docs", description: "PDF tools", branch: "trunk",
      skillFiles: ["skills/pdf/SKILL.md"], skillCount: 1,
    },
    {
      name: "obra/superpowers", owner: "obra", repo: "superpowers",
      url: "https://github.com/obra/superpowers",
      category: "Frameworks", description: "Disciplined TDD workflow", branch: "main",
      skillFiles: ["skills/brainstorming/SKILL.md", "skills/tdd/SKILL.md"], skillCount: 2,
    },
  ],
};

/** Register the catalog + a POST collector; returns the captured create bodies. */
function mockInstall() {
  const created: any[] = [];
  server.use(
    http.get(CATALOG_URL, () => HttpResponse.json(catalog)),
    http.post("/v1/skills", async ({ request }) => {
      const body = await request.json();
      created.push(body);
      return HttpResponse.json({ id: `skl_${created.length}`, ...(body as object), created_at: null, updated_at: null });
    }),
  );
  return created;
}

describe("SkillEditor — Recommended tab", () => {
  it("installs a single-skill repo with its subpath and branch", async () => {
    const created = mockInstall();
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Recommended" }));

    expect(screen.getByRole("button", { name: /install skill/i })).toBeDisabled();
    await userEvent.click(await screen.findByRole("button", { name: /acme\/pdf/i }));

    const install = screen.getByRole("button", { name: /install skill/i });
    await waitFor(() => expect(install).not.toBeDisabled());
    await userEvent.click(install);

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      source_type: "git", source_url: "https://github.com/acme/pdf",
      source_subpath: "skills/pdf", source_ref: "trunk",
    });
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/skills"));
  });

  it("expands a multi-skill repo and installs the chosen skill", async () => {
    const created = mockInstall();
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Recommended" }));

    await userEvent.click(await screen.findByRole("button", { name: /obra\/superpowers/i }));
    expect(screen.getByRole("button", { name: /install skill/i })).toBeDisabled();

    await userEvent.click(await screen.findByRole("button", { name: /brainstorming/i }));
    const install = screen.getByRole("button", { name: /install skill/i });
    await waitFor(() => expect(install).not.toBeDisabled());
    await userEvent.click(install);

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      source_type: "git", source_url: "https://github.com/obra/superpowers",
      source_subpath: "skills/brainstorming", source_ref: "main",
    });
  });

  it("installs multiple selected skills in one go", async () => {
    const created = mockInstall();
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Recommended" }));

    // Select a single-skill repo, then expand a multi-skill repo and add one.
    await userEvent.click(await screen.findByRole("button", { name: /acme\/pdf/i }));
    await userEvent.click(await screen.findByRole("button", { name: /obra\/superpowers/i }));
    await userEvent.click(await screen.findByRole("button", { name: /brainstorming/i }));

    // The button now reflects the multi-install count.
    const install = await screen.findByRole("button", { name: /install 2 skills/i });
    await userEvent.click(install);

    await waitFor(() => expect(created).toHaveLength(2));
    expect(created.map((c) => c.source_subpath).sort()).toEqual(
      ["skills/brainstorming", "skills/pdf"],
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/skills"));
  });

  it("toggles a selection off", async () => {
    mockInstall();
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Recommended" }));

    const pick = await screen.findByRole("button", { name: /acme\/pdf/i });
    await userEvent.click(pick);
    await waitFor(() => expect(screen.getByRole("button", { name: /install skill/i })).not.toBeDisabled());
    await userEvent.click(pick); // toggle off
    await waitFor(() => expect(screen.getByRole("button", { name: /install skill/i })).toBeDisabled());
  });

  it("filters repositories by search", async () => {
    server.use(http.get(CATALOG_URL, () => HttpResponse.json(catalog)));
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Recommended" }));
    await screen.findByRole("button", { name: /acme\/pdf/i });

    await userEvent.type(screen.getByLabelText("Search recommended skills"), "acme");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /obra\/superpowers/i })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: /acme\/pdf/i })).toBeInTheDocument();
  });
});
