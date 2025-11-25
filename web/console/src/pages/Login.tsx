import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { keys } from "../api/queries";
import { clearLog } from "../apiLog/store";
import type { Me } from "../api/types";
import { Logo } from "../ui/Logo";
import { AppssembleLogo } from "../ui/AppssembleLogo";

// Staggered entrance: drives the --d delay consumed by .lgn-rise in login.css.
const rise = (ms: number): React.CSSProperties => ({ ["--d" as string]: `${ms}ms` });

export default function Login() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/v1/auth/login", { email, password });
      // Load the FULL identity. The login response is a smaller shape that omits
      // is_staff, tenant names, and the active tenant object — seeding it directly
      // makes the app briefly mis-render (e.g. a staff user looks like a member).
      // Fetch /me and seed that, so RequireRole sees the real user immediately and
      // the redirect doesn't bounce back to /login.
      const me = await api.get<Me>("/v1/auth/me");
      queryClient.setQueryData(keys.me, me);
      clearLog(); // drop any prior session's API activity before the new user's session
      navigate(me.must_change_password ? "/change-password" : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  const invalid = error ? true : undefined;

  return (
    <div className="lgn">
      {/* Ink command surface — purely ambient, skipped by assistive tech. */}
      <aside className="lgn-stage" aria-hidden="true">
        <div className="lgn-grain" />
        <div className="lgn-stage-inner">
          <div className="lgn-mark lgn-rise" style={rise(40)}>
            <span className="lgn-logo-tile"><Logo size={22} /></span>
            <span className="lgn-logo-word">agenhood</span>
          </div>

          <div>
            <p className="lgn-kicker lgn-rise" style={rise(140)}>Fleet Console</p>
            <h2 className="lgn-display lgn-rise" style={rise(220)}>
              Full control over<br />
              <span className="lgn-accent">your agents.</span>
              <span className="lgn-caret" />
            </h2>
            <p className="lgn-lede lgn-rise" style={rise(320)}>
              Self-hosted agent infrastructure. You own your agents, your data, and your stack.
            </p>
          </div>

          <a
            className="lgn-status lgn-rise"
            style={rise(440)}
            href="https://appssemble.com"
            target="_blank"
            rel="noreferrer"
          >
            <AppssembleLogo size={16} className="lgn-by-logo" />
            Built by Appssemble
            <span className="lgn-status-sep">·</span>
            <span className="lgn-status-mono">agenhood/console</span>
          </a>
        </div>
      </aside>

      {/* Paper form column */}
      <main className="lgn-panel">
        <div className="lgn-form-wrap">
          <header className="lgn-head">
            <p className="lgn-eyebrow lgn-rise" style={rise(120)}>Welcome back</p>
            <h1 className="lgn-title lgn-rise" style={rise(180)}>Sign in</h1>
          </header>

          <form onSubmit={onSubmit} className="lgn-form" noValidate aria-busy={busy}>
            <div className="lgn-field lgn-rise" data-invalid={invalid} style={rise(260)}>
              <input
                id="email"
                className="lgn-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
                aria-invalid={invalid}
                aria-describedby={error ? "lgn-error" : undefined}
                required
              />
              <label htmlFor="email" className="lgn-label">Email</label>
            </div>

            <div className="lgn-field lgn-rise" data-invalid={invalid} style={rise(320)}>
              <input
                id="password"
                className="lgn-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
                aria-invalid={invalid}
                aria-describedby={error ? "lgn-error" : undefined}
                required
              />
              <label htmlFor="password" className="lgn-label">Password</label>
            </div>

            {error && (
              <div id="lgn-error" className="lgn-alert lgn-rise" role="alert">
                <span className="lgn-alert-mark" aria-hidden="true" />
                {error}
              </div>
            )}

            <button type="submit" className="lgn-submit lgn-rise" style={rise(380)} disabled={busy}>
              <span>{busy ? "Signing in…" : "Sign in"}</span>
              {busy
                ? <span className="lgn-spin" aria-hidden="true" />
                : <span className="lgn-arrow" aria-hidden="true">→</span>}
            </button>
          </form>

          <p className="lgn-foot lgn-rise" style={rise(460)}>
            Trouble signing in? <a className="lgn-link" href="mailto:support@agenhood.com">Contact your workspace admin</a>.
          </p>
        </div>
      </main>
    </div>
  );
}
