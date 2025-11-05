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
];
