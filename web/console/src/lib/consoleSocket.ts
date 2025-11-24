import { API_BASE } from "../api/base";
// Dev-only: an explicit ws(s):// origin for the console socket. The vite dev
// proxy forwards HTTP/SSE but not WebSocket upgrades, so dev points this at the
// control-plane's published port. Unset in prod → same-origin (through Traefik).
const CONSOLE_WS_BASE = import.meta.env.VITE_CONSOLE_WS_BASE as string | undefined;

interface Loc {
  protocol: string;
  host: string;
}

/**
 * Build the WebSocket URL for a container console. Precedence:
 *   1. VITE_CONSOLE_WS_BASE (explicit ws origin; dev direct-connect)
 *   2. VITE_API_BASE (explicit http origin → ws)
 *   3. the page's own origin (prod same-origin)
 * The session cookie is sent automatically on the handshake (cookies are scoped
 * by domain, not port, so a direct connect to a different port still carries it).
 */
export function consoleWsUrl(
  cid: string,
  loc: Loc = window.location,
  base: string = API_BASE,
  wsBase: string | undefined = CONSOLE_WS_BASE,
): string {
  const path = `/v1/containers/${cid}/console`;
  if (wsBase) {
    return wsBase.replace(/\/$/, "") + path;
  }
  if (base && /^https?:\/\//.test(base)) {
    return base.replace(/^http/, "ws").replace(/\/$/, "") + path;
  }
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.host}${path}`;
}
