"""Route-contract registry for the control-plane API meta-gate (Unit C, Task 2).

contracts.py defines:
- make_app()                — canonical test app instance
- iter_mutation_routes(app) — prefix-folding enumerator → (full_path, APIRoute)
- ALLOW                     — (METHOD, path) pairs reviewed and explicitly exempt
- CONTRACTS                 — full (method, path_template, sample_url, kind) matrix

Live route count: 124 (as of 2026-07-14, after the /v1/containers/{cid}/env GET+PUT add).
  ALLOW: 2 (GET /docs/oauth2-redirect + WEBSOCKET console — framework/ws, not HTTP-testable)
  CONTRACTS: 122 (auth 116 + public 3 + redirect 3)

Reconciliation vs AUDIT.md (117 as of 2026-06-30):
  The AUDIT missed WEBSOCKET /v1/containers/{cid}/console and GET /docs/oauth2-redirect
  which appear in collect_routes() but not in the 117-route AUDIT tally.  Both are
  ALLOW'd — the websocket is not testable via AsyncClient HTTP; the oauth2-redirect
  is a FastAPI framework route registered at /docs/oauth2-redirect instead of the
  computed /v1/docs/oauth2-redirect (mismatch in _framework_defaults).
  The three /v1/deploy-keys routes (GET/POST/DELETE, all require_admin) were added
  on top of that baseline and are covered below as "auth".
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from control_plane.app import create_app
from control_plane.auth.principal import Principal
from control_plane.config import Settings

# ---------------------------------------------------------------------------
# Canonical settings (no real DB needed for the 401-gate).
# ---------------------------------------------------------------------------
_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)


def make_app() -> FastAPI:
    """Return a fully-configured control-plane app for contract testing."""
    return create_app(_SETTINGS)


def iter_mutation_routes(app: FastAPI) -> list[tuple[str, APIRoute]]:
    """Enumerate every APIRoute with its full registered path (including /v1 prefix).

    Folds include_context.prefix exactly like collect_routes() in
    agentcore.testing.route_inventory, so returned paths are the same full
    /v1-prefixed paths used by CONTRACTS and SELF_SCOPED_MUTATIONS.

    Returns a list of (full_path, APIRoute) pairs for all routes.
    """
    result: list[tuple[str, APIRoute]] = []

    def _walk(routes: list, prefix: str) -> None:
        for r in routes:
            path = prefix + getattr(r, "path", "")
            if isinstance(r, APIRoute):
                result.append((path, r))
            else:
                # _IncludedRouter wrapper or Mount: fold include_context.prefix
                # (carries the /v1 prefix from include_router(prefix="/v1"))
                # then recurse into sub-routes — mirrors route_inventory._walk.
                ctx = getattr(r, "include_context", None)
                ctx_prefix = getattr(ctx, "prefix", "") or ""
                original = getattr(r, "original_router", None)
                sub = getattr(r, "routes", None) or getattr(original, "routes", None)
                if sub:
                    _walk(sub, path + ctx_prefix)

    _walk(app.routes, "")
    return result


# ---------------------------------------------------------------------------
# ALLOW: routes appearing in collect_routes() that intentionally have NO
# contract test.  Must be (METHOD, path) tuples to match RoutePair.
# Every entry is reviewed; stale entries cause assert_routes_covered to fail.
# ---------------------------------------------------------------------------
ALLOW: set[tuple[str, str]] = {
    # FastAPI registers the OAuth2 redirect at the hardcoded path /docs/oauth2-redirect,
    # but _framework_defaults computes /v1/docs/oauth2-redirect (mismatch) so it
    # survives into collect_routes.  Framework-generated, no handler logic to test.
    ("GET", "/docs/oauth2-redirect"),
    # WebSocket route: not testable via AsyncClient HTTP requests.
    ("WEBSOCKET", "/v1/containers/{cid}/console"),
}

# ---------------------------------------------------------------------------
# Shared principals (imported by Task 3 role-matrix tests).
# ---------------------------------------------------------------------------
P_MEMBER = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_m")
P_ADMIN = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")
P_OWNER = Principal(tenant_id="ten_1", role="owner", is_staff=False, user_id="usr_o")
P_STAFF = Principal(tenant_id=None, role="member", is_staff=True, user_id="usr_s")
P_APIKEY = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)

# ---------------------------------------------------------------------------
# SELF_SCOPED_MUTATIONS: mutation routes (POST/PATCH/DELETE/PUT) whose
# authorisation is NOT enforced by a require_* gate dependency.  Instead each
# handler either:
#   (a) is intentionally public (login / logout — no auth needed);
#   (b) performs self/ownership checks inside the handler body; or
#   (c) uses the _principal() wrapper (= resolve_principal + tenant_id guard)
#       and then enforces tenant ownership via DB filtering inside the handler.
#
# This set is the reviewed allow-list consumed by the gate-class meta-gate in
# test_role_matrix_gate.py.  Every entry here is an EXPLICIT claim that the
# route self-authorises; a wrong entry hides a real auth gap.
#
# Paths are full registered paths (with /v1) matching collect_routes/CONTRACTS.
# ---------------------------------------------------------------------------
SELF_SCOPED_MUTATIONS: set[str] = {
    # Public: unauthenticated POSTs are intentional (no auth dependency).
    "/v1/auth/login",    # creates a session cookie — no prior auth needed
    "/v1/auth/logout",   # revokes session; intentionally unauthenticated

    # Self-scoped: resolve_principal; handler checks own identity / role.
    "/v1/auth/select-tenant",    # rejects API-key principals inside handler
    "/v1/users/{uid}/password",  # allows self-change OR admin; checked inside
    "/v1/tenants",               # self-serve cap-checked inside handler (POST)

    # Templates clone — resolve_principal; any tenant user may clone.
    "/v1/templates/{template_id}/clone",

    # ------------------------------------------------------------------
    # Container lifecycle — _principal wrapper (= resolve_principal +
    # tenant_id guard).  Handler enforces tenant ownership via DB filter.
    # ------------------------------------------------------------------
    "/v1/containers",                              # create; capped by tenant limits
    "/v1/containers/{cid}",                        # DELETE (destroy alias / remove)
    "/v1/containers/{cid}/config",                 # PATCH config
    "/v1/containers/{cid}/env",                    # PUT env vars
    "/v1/containers/{cid}/destroy",                # POST lifecycle
    "/v1/containers/{cid}/pause",                  # POST lifecycle
    "/v1/containers/{cid}/resources",              # PATCH lifecycle
    "/v1/containers/{cid}/restore",                # POST lifecycle
    "/v1/containers/{cid}/resume",                 # POST lifecycle
    "/v1/containers/{cid}/update-image",           # POST lifecycle

    # Container git mutations — _principal
    "/v1/containers/{cid}/git/link",               # POST + DELETE
    "/v1/containers/{cid}/git/link/key",           # POST
    "/v1/containers/{cid}/git/link/repull",        # POST
    "/v1/containers/{cid}/git/link/verify",        # POST
    "/v1/containers/{cid}/git/push",               # POST
    "/v1/containers/{cid}/git/remote",             # PUT + DELETE
    "/v1/containers/{cid}/git/remote/key",         # POST
    "/v1/containers/{cid}/git/remote/verify",      # POST
    "/v1/containers/{cid}/git/rollback",           # POST

    # Container file mutations — _principal
    "/v1/containers/{cid}/files/raw",              # PUT + DELETE

    # Container task mutations — _principal
    "/v1/containers/{cid}/tasks",                  # POST submit
    "/v1/containers/{cid}/tasks/from-prompt",      # POST submit-from-prompt
    "/v1/containers/{cid}/tasks/{tid}/cancel",     # POST cancel

    # Container-scoped scheduled-tasks — _principal (POST, PATCH).
    # The DELETE at this same path is the 308 legacy redirect shim;
    # actual auth happens at the redirect target (/v1/scheduled-tasks/{sid}).
    "/v1/containers/{cid}/scheduled-tasks",        # POST
    "/v1/containers/{cid}/scheduled-tasks/{sid}",  # PATCH (+ legacy DELETE 308 shim)

    # ------------------------------------------------------------------
    # Tenant CRUD — plain resolve_principal; handler filters by tenant_id.
    # ------------------------------------------------------------------
    "/v1/prompts",              # POST
    "/v1/prompts/{pid}",        # PATCH + DELETE
    "/v1/workflows",            # POST
    "/v1/workflows/{wid}",      # PATCH + DELETE
    "/v1/workflows/{wid}/run",  # POST
    "/v1/scheduled-tasks",      # POST
    "/v1/scheduled-tasks/{sid}", # PATCH + DELETE
}

# ---------------------------------------------------------------------------
# CONTRACTS: (method, path_template, sample_url, kind)
#   path_template — matches collect_routes() RoutePair path (full registered path)
#   sample_url    — concrete URL used in the parametrized request (path params filled)
#   kind          — "auth" | "public" | "redirect"
#
# "auth":     no-credentials request → 401 + error.code == "unauthorized"
# "public":   no-credentials request → any status except 401
# "redirect": no-credentials request → 307 or 308 with Location header
#
# All 117 AUDIT routes plus later additions are covered here
# (auth=116, public=3, redirect=3).
# ---------------------------------------------------------------------------
CONTRACTS: list[tuple[str, str, str, str]] = [
    # ------------------------------------------------------------------
    # PUBLIC: no auth dependency, reachable without credentials
    # ------------------------------------------------------------------
    ("GET",  "/healthz",       "/healthz",       "public"),
    ("POST", "/v1/auth/login", "/v1/auth/login", "public"),
    ("POST", "/v1/auth/logout", "/v1/auth/logout", "public"),

    # ------------------------------------------------------------------
    # REDIRECT: 308 legacy container-scoped scheduled-tasks shims
    # ------------------------------------------------------------------
    ("GET",    "/v1/containers/{cid}/scheduled-tasks",
               "/v1/containers/c_x/scheduled-tasks",     "redirect"),
    ("GET",    "/v1/containers/{cid}/scheduled-tasks/{sid}",
               "/v1/containers/c_x/scheduled-tasks/s_x", "redirect"),
    ("DELETE", "/v1/containers/{cid}/scheduled-tasks/{sid}",
               "/v1/containers/c_x/scheduled-tasks/s_x", "redirect"),

    # ------------------------------------------------------------------
    # AUTH: admin API (/admin/v1/...)
    # All require require_staff → 401 for no-principal
    # ------------------------------------------------------------------
    ("GET",    "/admin/v1/health",        "/admin/v1/health",      "auth"),
    ("GET",    "/admin/v1/staff",         "/admin/v1/staff",       "auth"),
    ("POST",   "/admin/v1/staff",         "/admin/v1/staff",       "auth"),
    ("PATCH",  "/admin/v1/staff/{uid}",   "/admin/v1/staff/u_x",   "auth"),
    ("GET",    "/admin/v1/tenants",       "/admin/v1/tenants",     "auth"),
    ("POST",   "/admin/v1/tenants",       "/admin/v1/tenants",     "auth"),
    ("DELETE", "/admin/v1/tenants/{tid}", "/admin/v1/tenants/t_x", "auth"),
    ("PATCH",  "/admin/v1/tenants/{tid}", "/admin/v1/tenants/t_x", "auth"),
    ("GET",    "/admin/v1/users",         "/admin/v1/users",       "auth"),

    # ------------------------------------------------------------------
    # AUTH: analytics
    # ------------------------------------------------------------------
    ("GET", "/v1/analytics/breakdown", "/v1/analytics/breakdown", "auth"),
    ("GET", "/v1/analytics/usage",     "/v1/analytics/usage",     "auth"),

    # ------------------------------------------------------------------
    # AUTH: api-keys (require_session_admin → 401 for no-principal)
    # ------------------------------------------------------------------
    ("GET",    "/v1/api-keys",       "/v1/api-keys",     "auth"),
    ("POST",   "/v1/api-keys",       "/v1/api-keys",     "auth"),
    ("DELETE", "/v1/api-keys/{kid}", "/v1/api-keys/k_x", "auth"),

    # ------------------------------------------------------------------
    # AUTH: auth sub-routes (public login/logout already listed above)
    # ------------------------------------------------------------------
    ("GET",  "/v1/auth/me",            "/v1/auth/me",            "auth"),
    ("POST", "/v1/auth/select-tenant", "/v1/auth/select-tenant", "auth"),

    # ------------------------------------------------------------------
    # AUTH: containers
    # ------------------------------------------------------------------
    ("GET",    "/v1/containers",        "/v1/containers",     "auth"),
    ("POST",   "/v1/containers",        "/v1/containers",     "auth"),
    ("GET",    "/v1/containers/{cid}",  "/v1/containers/c_x", "auth"),
    ("DELETE", "/v1/containers/{cid}",  "/v1/containers/c_x", "auth"),
    ("GET",    "/v1/containers/{cid}/config",  "/v1/containers/c_x/config",  "auth"),
    ("PATCH",  "/v1/containers/{cid}/config",  "/v1/containers/c_x/config",  "auth"),
    ("GET",    "/v1/containers/{cid}/env",     "/v1/containers/c_x/env",     "auth"),
    ("PUT",    "/v1/containers/{cid}/env",     "/v1/containers/c_x/env",     "auth"),
    ("POST",   "/v1/containers/{cid}/destroy", "/v1/containers/c_x/destroy", "auth"),
    ("GET",    "/v1/containers/{cid}/files",   "/v1/containers/c_x/files",   "auth"),
    ("GET",    "/v1/containers/{cid}/files/archive",
     "/v1/containers/c_x/files/archive", "auth"),
    ("GET",    "/v1/containers/{cid}/files/raw",
     "/v1/containers/c_x/files/raw", "auth"),
    ("PUT",    "/v1/containers/{cid}/files/raw",
     "/v1/containers/c_x/files/raw", "auth"),
    ("DELETE", "/v1/containers/{cid}/files/raw",
     "/v1/containers/c_x/files/raw", "auth"),
    ("DELETE", "/v1/containers/{cid}/git/link",
     "/v1/containers/c_x/git/link", "auth"),
    ("GET",    "/v1/containers/{cid}/git/link",
     "/v1/containers/c_x/git/link", "auth"),
    ("POST",   "/v1/containers/{cid}/git/link",
     "/v1/containers/c_x/git/link", "auth"),
    ("POST",   "/v1/containers/{cid}/git/link/key",
     "/v1/containers/c_x/git/link/key", "auth"),
    ("POST",   "/v1/containers/{cid}/git/link/repull",
     "/v1/containers/c_x/git/link/repull", "auth"),
    ("POST",   "/v1/containers/{cid}/git/link/verify",
     "/v1/containers/c_x/git/link/verify", "auth"),
    ("POST",   "/v1/containers/{cid}/git/push",
     "/v1/containers/c_x/git/push", "auth"),
    ("DELETE", "/v1/containers/{cid}/git/remote",
     "/v1/containers/c_x/git/remote", "auth"),
    ("GET",    "/v1/containers/{cid}/git/remote",
     "/v1/containers/c_x/git/remote", "auth"),
    ("PUT",    "/v1/containers/{cid}/git/remote",
     "/v1/containers/c_x/git/remote", "auth"),
    ("POST",   "/v1/containers/{cid}/git/remote/key",
     "/v1/containers/c_x/git/remote/key", "auth"),
    ("POST",   "/v1/containers/{cid}/git/remote/verify",
     "/v1/containers/c_x/git/remote/verify", "auth"),
    ("POST",   "/v1/containers/{cid}/git/rollback",
     "/v1/containers/c_x/git/rollback", "auth"),
    ("GET",    "/v1/containers/{cid}/git/snapshots",
     "/v1/containers/c_x/git/snapshots", "auth"),
    ("POST",   "/v1/containers/{cid}/pause",   "/v1/containers/c_x/pause",   "auth"),
    ("POST",   "/v1/containers/{cid}/recover", "/v1/containers/c_x/recover", "auth"),
    ("PATCH",  "/v1/containers/{cid}/resources",
     "/v1/containers/c_x/resources", "auth"),
    ("POST",   "/v1/containers/{cid}/restore", "/v1/containers/c_x/restore", "auth"),
    ("POST",   "/v1/containers/{cid}/resume",  "/v1/containers/c_x/resume",  "auth"),
    ("POST",   "/v1/containers/{cid}/scheduled-tasks",
     "/v1/containers/c_x/scheduled-tasks", "auth"),
    ("PATCH",  "/v1/containers/{cid}/scheduled-tasks/{sid}",
     "/v1/containers/c_x/scheduled-tasks/s_x", "auth"),
    ("GET",    "/v1/containers/{cid}/sessions",
     "/v1/containers/c_x/sessions", "auth"),
    ("GET",    "/v1/containers/{cid}/tasks", "/v1/containers/c_x/tasks", "auth"),
    ("POST",   "/v1/containers/{cid}/tasks", "/v1/containers/c_x/tasks", "auth"),
    ("POST",   "/v1/containers/{cid}/tasks/from-prompt",
     "/v1/containers/c_x/tasks/from-prompt", "auth"),
    ("GET",    "/v1/containers/{cid}/tasks/{tid}",
     "/v1/containers/c_x/tasks/t_x", "auth"),
    ("POST",   "/v1/containers/{cid}/tasks/{tid}/cancel",
     "/v1/containers/c_x/tasks/t_x/cancel", "auth"),
    ("GET",    "/v1/containers/{cid}/tasks/{tid}/events",
     "/v1/containers/c_x/tasks/t_x/events", "auth"),
    ("POST",   "/v1/containers/{cid}/update-image",
     "/v1/containers/c_x/update-image", "auth"),

    # ------------------------------------------------------------------
    # AUTH: credentials (require_session_admin → 401 for no-principal)
    # ------------------------------------------------------------------
    ("GET",    "/v1/credentials",        "/v1/credentials",        "auth"),
    ("POST",   "/v1/credentials",        "/v1/credentials",        "auth"),
    ("DELETE", "/v1/credentials/{cid}",  "/v1/credentials/cred_x", "auth"),
    ("GET",    "/v1/credentials/_internal/decrypt/{cid}",
     "/v1/credentials/_internal/decrypt/cred_x", "auth"),
    ("POST",   "/v1/credentials/oauth/anthropic/complete",
     "/v1/credentials/oauth/anthropic/complete", "auth"),
    ("POST",   "/v1/credentials/oauth/anthropic/start",
     "/v1/credentials/oauth/anthropic/start", "auth"),
    ("GET",    "/v1/credentials/oauth/openai/connections/{connection_id}",
     "/v1/credentials/oauth/openai/connections/conn_x", "auth"),
    ("GET",
     "/v1/credentials/oauth/openai/connections/{connection_id}/events",
     "/v1/credentials/oauth/openai/connections/conn_x/events", "auth"),
    ("POST",   "/v1/credentials/oauth/openai/start",
     "/v1/credentials/oauth/openai/start", "auth"),
    ("GET",    "/v1/credentials/providers", "/v1/credentials/providers", "auth"),

    # ------------------------------------------------------------------
    # AUTH: deploy-keys (require_admin → 401 for no-principal)
    # ------------------------------------------------------------------
    ("GET",    "/v1/deploy-keys",         "/v1/deploy-keys",       "auth"),
    ("POST",   "/v1/deploy-keys",         "/v1/deploy-keys",       "auth"),
    ("DELETE", "/v1/deploy-keys/{dkid}",  "/v1/deploy-keys/dk_x",  "auth"),

    # ------------------------------------------------------------------
    # AUTH: images
    # ------------------------------------------------------------------
    ("GET", "/v1/images/tags", "/v1/images/tags", "auth"),

    # ------------------------------------------------------------------
    # AUTH: mcp-servers
    # ------------------------------------------------------------------
    ("GET",    "/v1/mcp-servers",       "/v1/mcp-servers",     "auth"),
    ("POST",   "/v1/mcp-servers",       "/v1/mcp-servers",     "auth"),
    ("DELETE", "/v1/mcp-servers/{mid}", "/v1/mcp-servers/m_x", "auth"),
    ("GET",    "/v1/mcp-servers/{mid}", "/v1/mcp-servers/m_x", "auth"),
    ("PATCH",  "/v1/mcp-servers/{mid}", "/v1/mcp-servers/m_x", "auth"),

    # ------------------------------------------------------------------
    # AUTH: models
    # ------------------------------------------------------------------
    ("GET", "/v1/models", "/v1/models", "auth"),

    # ------------------------------------------------------------------
    # AUTH: prompts
    # ------------------------------------------------------------------
    ("GET",    "/v1/prompts",       "/v1/prompts",     "auth"),
    ("POST",   "/v1/prompts",       "/v1/prompts",     "auth"),
    ("DELETE", "/v1/prompts/{pid}", "/v1/prompts/p_x", "auth"),
    ("GET",    "/v1/prompts/{pid}", "/v1/prompts/p_x", "auth"),
    ("PATCH",  "/v1/prompts/{pid}", "/v1/prompts/p_x", "auth"),

    # ------------------------------------------------------------------
    # AUTH: scheduled-tasks (tenant-scoped, at /v1/scheduled-tasks)
    # ------------------------------------------------------------------
    ("GET",    "/v1/scheduled-tasks",       "/v1/scheduled-tasks",     "auth"),
    ("POST",   "/v1/scheduled-tasks",       "/v1/scheduled-tasks",     "auth"),
    ("DELETE", "/v1/scheduled-tasks/{sid}", "/v1/scheduled-tasks/s_x", "auth"),
    ("GET",    "/v1/scheduled-tasks/{sid}", "/v1/scheduled-tasks/s_x", "auth"),
    ("PATCH",  "/v1/scheduled-tasks/{sid}", "/v1/scheduled-tasks/s_x", "auth"),

    # ------------------------------------------------------------------
    # AUTH: skills
    # ------------------------------------------------------------------
    ("GET",    "/v1/skills",              "/v1/skills",              "auth"),
    ("POST",   "/v1/skills",              "/v1/skills",              "auth"),
    ("POST",   "/v1/skills/git-refs",     "/v1/skills/git-refs",     "auth"),
    ("POST",   "/v1/skills/git-discover", "/v1/skills/git-discover", "auth"),
    ("DELETE", "/v1/skills/{sid}",        "/v1/skills/sk_x",         "auth"),
    ("GET",    "/v1/skills/{sid}",        "/v1/skills/sk_x",         "auth"),
    ("PATCH",  "/v1/skills/{sid}",        "/v1/skills/sk_x",         "auth"),
    ("POST",   "/v1/skills/{sid}/refresh", "/v1/skills/sk_x/refresh", "auth"),

    # ------------------------------------------------------------------
    # AUTH: tasks (tenant-scoped, at /v1/tasks)
    # ------------------------------------------------------------------
    ("GET", "/v1/tasks", "/v1/tasks", "auth"),

    # ------------------------------------------------------------------
    # AUTH: templates
    # ------------------------------------------------------------------
    ("GET",    "/v1/templates",                     "/v1/templates",          "auth"),
    ("POST",   "/v1/templates",                     "/v1/templates",          "auth"),
    ("DELETE", "/v1/templates/{template_id}",       "/v1/templates/tmpl_x",   "auth"),
    ("GET",    "/v1/templates/{template_id}",       "/v1/templates/tmpl_x",   "auth"),
    ("PATCH",  "/v1/templates/{template_id}",       "/v1/templates/tmpl_x",   "auth"),
    ("POST",   "/v1/templates/{template_id}/clone", "/v1/templates/tmpl_x/clone", "auth"),

    # ------------------------------------------------------------------
    # AUTH: tenants (self-serve workspace creation)
    # ------------------------------------------------------------------
    ("POST", "/v1/tenants", "/v1/tenants", "auth"),

    # ------------------------------------------------------------------
    # AUTH: users (require_session_admin → 401 for no-principal)
    # ------------------------------------------------------------------
    ("GET",    "/v1/users",                "/v1/users",             "auth"),
    ("POST",   "/v1/users",                "/v1/users",             "auth"),
    ("DELETE", "/v1/users/{uid}",          "/v1/users/u_x",         "auth"),
    ("PATCH",  "/v1/users/{uid}",          "/v1/users/u_x",         "auth"),
    ("POST",   "/v1/users/{uid}/password", "/v1/users/u_x/password", "auth"),

    # ------------------------------------------------------------------
    # AUTH: workflows
    # ------------------------------------------------------------------
    ("GET",    "/v1/workflows",        "/v1/workflows",     "auth"),
    ("POST",   "/v1/workflows",        "/v1/workflows",     "auth"),
    ("DELETE", "/v1/workflows/{wid}",  "/v1/workflows/w_x", "auth"),
    ("GET",    "/v1/workflows/{wid}",  "/v1/workflows/w_x", "auth"),
    ("PATCH",  "/v1/workflows/{wid}",  "/v1/workflows/w_x", "auth"),
    ("POST",   "/v1/workflows/{wid}/run",  "/v1/workflows/w_x/run",  "auth"),
    ("GET",    "/v1/workflows/{wid}/runs", "/v1/workflows/w_x/runs", "auth"),
    ("GET",    "/v1/workflows/{wid}/runs/{run_id}",
     "/v1/workflows/w_x/runs/r_x", "auth"),
    ("GET",    "/v1/workflows/{wid}/runs/{run_id}/events",
     "/v1/workflows/w_x/runs/r_x/events", "auth"),
]
