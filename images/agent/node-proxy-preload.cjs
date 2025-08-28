'use strict';
/*
 * Make Node's built-in `fetch`/undici honor HTTP(S)_PROXY / NO_PROXY env vars.
 *
 * Node's bundled undici (which powers the global `fetch`) ignores the proxy
 * environment variables that curl, git and Python all respect. In the agent
 * sandbox the ONLY egress path is the egress proxy (direct egress is blocked at
 * the network), so any `fetch()` in a workspace script — e.g. a model-run
 * *.mjs — fails with EAI_AGAIN. This preload installs a global
 * EnvHttpProxyAgent dispatcher so every Node process routes `fetch` through the
 * proxy while still honoring NO_PROXY (localhost, searxng, …).
 *
 * Loaded into every node process via NODE_OPTIONS=--require (see the agent
 * Dockerfile). It MUST NEVER throw: a throwing --require preload would break
 * every `node` invocation in the image, so the whole body is guarded and the
 * undici dependency is optional (no-op if absent).
 */
try {
  const hasProxy =
    process.env.HTTPS_PROXY || process.env.https_proxy ||
    process.env.HTTP_PROXY || process.env.http_proxy;
  if (hasProxy) {
    // Isolated install (see Dockerfile) — never the app's own undici, so we
    // don't perturb opencode/claude-code dependency resolution.
    const { setGlobalDispatcher, EnvHttpProxyAgent } = require('/opt/node-proxy/node_modules/undici');
    if (typeof EnvHttpProxyAgent === 'function') {
      // EnvHttpProxyAgent is flagged experimental and emits a one-time
      // UNDICI-EHPA process warning; filter just that code so it never
      // pollutes script stdout/stderr (other warnings pass through).
      const origEmitWarning = process.emitWarning;
      process.emitWarning = function (warning, ...rest) {
        const code = (rest[0] && rest[0].code) || rest[1];
        if (code === 'UNDICI-EHPA') return undefined;
        return origEmitWarning.call(process, warning, ...rest);
      };
      // EnvHttpProxyAgent reads HTTP_PROXY/HTTPS_PROXY/NO_PROXY from the env.
      setGlobalDispatcher(new EnvHttpProxyAgent());
    }
  }
} catch (err) {
  // Opt-in diagnostics only; silent by default so we never disrupt tooling.
  if (process.env.NODE_PROXY_PRELOAD_DEBUG) {
    try { console.error('[node-proxy-preload] disabled:', err && err.message); } catch (_) { /* ignore */ }
  }
}
