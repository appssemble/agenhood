// Exact field names whose values are always masked. Matching is by exact name
// (case-insensitive), NOT substring, so intentionally-safe fields like
// `last4`, `token_last4`, `prefix`, and `account_tail` stay visible for debugging.
const SENSITIVE = new Set([
  "password",
  "current_password",
  "new_password",
  "secret",
  "client_secret",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "api_key",
  "apikey",
  "key",
  "private_key",
  "credential",
  "authorization",
]);

// Value-level safety net: mask secrets by their shape regardless of field name,
// so a key or bearer token leaking into an unexpected field or free-text string
// is still caught. Kept deliberately narrow to avoid masking legitimate content:
//   - issued API keys (tk_live_… / tk_test_… prefix)
//   - Authorization bearer tokens
const API_KEY_RE = /(tk_(?:live|test)_)[A-Za-z0-9]+/g;
const BEARER_RE = /(Bearer\s+)[\w.-]+/gi;

function scrubString(s: string): string {
  return s.replace(API_KEY_RE, "$1***").replace(BEARER_RE, "$1***");
}

// Returns a deep copy with sensitive fields masked and secret-shaped values
// scrubbed. Input is always JSON-serializable (request bodies are
// JSON.stringify'd, responses are JSON.parse'd), so there are no circular
// references to guard against.
export function redact(value: unknown): unknown {
  if (typeof value === "string") return scrubString(value);
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SENSITIVE.has(k.toLowerCase()) ? "***" : redact(v);
    }
    return out;
  }
  return value;
}
