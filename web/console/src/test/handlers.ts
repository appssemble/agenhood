import { http, HttpResponse } from "msw";
import type { RequestHandler } from "msw";

// Default happy-path handlers are added by page tests; start (almost) empty.
// The New skill screen now defaults to the Recommended tab, which fetches the
// curated catalog on mount — stub it globally to a quiet empty list so the
// fetch never hits the network. Tests that exercise the catalog override this
// with server.use().
export const handlers: RequestHandler[] = [
  http.get(
    "https://raw.githubusercontent.com/appssemble/awesome-skill-md/main/skills.json",
    () => HttpResponse.json({ skills: [] }),
  ),
  // The skill editor's "Repository access" picker fetches deploy keys unconditionally
  // on mount (all tabs); default to none so tests that don't care about deploy keys
  // don't need their own stub. Override with server.use() to exercise the picker.
  http.get("/v1/deploy-keys", () => HttpResponse.json({ deploy_keys: [] })),
  // The git create-form's discovered-skills picker scans the repo as soon as
  // the URL and ref resolve; default to an empty, non-erroring scan so tests
  // that only care about the URL/ref/deploy-key flow don't need their own
  // stub. Tests exercising the picker itself override this with server.use().
  http.post(
    "/v1/skills/git-discover",
    () => HttpResponse.json({ ok: true, pinned_sha: "", truncated: false, skills: [] }),
  ),
];
