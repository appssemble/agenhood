import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import SkillEditor from "./SkillEditor";
import { urlError } from "../../lib/skillSource";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({}),            // no :id -> create mode
  useNavigate: () => navigate,
}));

describe("SkillEditor (create mode)", () => {
  it("POSTs a new inline skill and returns to the list", async () => {
    let created: any = null;
    server.use(
      http.post("/v1/skills", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json({ id: "skl_2", ...created, created_at: null, updated_at: null });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "lint");
    await userEvent.type(screen.getByLabelText("Description"), "Run linters");
    await userEvent.type(screen.getByLabelText("Instructions"), "# lint steps");
    await userEvent.click(screen.getByRole("button", { name: /save skill/i }));
    await waitFor(() => expect(created).toMatchObject({ name: "lint", description: "Run linters" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/settings/skills"));
  });

  it("shows a validation hint for an invalid name", async () => {
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "Bad Name");
    expect(screen.getByText(/lowercase|a-z0-9|hyphen/i)).toBeInTheDocument();
  });

  it("renders a live SKILL.md preview from the entered fields", async () => {
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "Inline" }));
    await userEvent.type(await screen.findByLabelText("Name"), "lint");
    await userEvent.type(screen.getByLabelText("Description"), "Run linters");
    expect(screen.getByText(/name: lint/)).toBeInTheDocument();
  });
});

describe("urlError", () => {
  it("accepts an https URL and rejects others", () => {
    expect(urlError("")).toBeNull();
    expect(urlError("https://github.com/org/repo")).toBeNull();
    expect(urlError("git@github.com:org/repo.git")).toMatch(/https/i);
    expect(urlError("http://github.com/org/repo")).toMatch(/https/i);
  });
});

describe("SkillEditor (git source)", () => {
  it("validates the URL and loads the branch combobox on blur", async () => {
    let asked: any = null;
    server.use(
      http.post("/v1/skills/git-refs", async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await userEvent.click(await screen.findByRole("button", { name: "From git" }));

    const url = screen.getByLabelText("Repository URL");
    const ref = screen.getByLabelText("Ref");
    expect(ref).toBeDisabled();              // disabled until refs load

    // Invalid scheme shows a hint and does not load branches.
    await userEvent.type(url, "git@github.com:org/repo.git");
    await userEvent.tab();
    expect(screen.getByText(/https:\/\//)).toBeInTheDocument();
    expect(asked).toBeNull();

    // A valid https URL loads branches and prefills the default ref.
    await userEvent.clear(url);
    await userEvent.type(url, "https://github.com/org/repo");
    await userEvent.tab();
    await waitFor(() => expect(asked).toMatchObject({ source_url: "https://github.com/org/repo" }));
    await waitFor(() => expect(ref).not.toBeDisabled());
    await waitFor(() => expect(ref).toHaveValue("main"));
    expect(document.querySelectorAll("#git-branches option")).toHaveLength(2);
  });
});
