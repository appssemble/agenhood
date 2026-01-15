import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import SkillEditor from "./SkillEditor";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({ id: "skl_1" }),   // edit mode
  useNavigate: () => navigate,
}));

describe("SkillEditor (edit mode)", () => {
  it("fetches the full skill (incl. body) and populates the editor", async () => {
    let detailFetched = false;
    server.use(
      http.get("/v1/skills/skl_1", () => {
        detailFetched = true;
        return HttpResponse.json({
          id: "skl_1", name: "git-release", description: "Make releases",
          enabled: true, source_type: "inline", body: "# the full body",
          created_at: null, updated_at: null,
        });
      }),
    );
    renderWithProviders(<SkillEditor />);
    await waitFor(() => expect(detailFetched).toBe(true));
    // The body textarea is populated from the detail fetch, not the list summary.
    await waitFor(() => expect(screen.getByDisplayValue("# the full body")).toBeInTheDocument());
  });
});
