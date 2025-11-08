const SESSION_ONLY_PREFIXES = ["/v1/auth", "/v1/users", "/v1/api-keys", "/v1/credentials"];

// Endpoints not callable with an API key (require_session_admin on the backend).
export function isSessionOnly(path: string): boolean {
  const p = path.split("?")[0];
  return SESSION_ONLY_PREFIXES.some((pre) => p === pre || p.startsWith(pre + "/"));
}

export interface CurlInput {
  method: string;
  path: string;
  requestBody?: unknown;
}

// Builds the public-API equivalent of a console call, with an API-key placeholder.
// requestBody must already be redacted by the caller.
export function toCurl(input: CurlInput, origin: string): string {
  const lines = [`curl -X ${input.method} ${origin}${input.path}`];
  const tail = `  -H "Authorization: Bearer tk_live_***"`;
  if (input.requestBody !== undefined) {
    lines.push(tail);
    lines.push(`  -H "Content-Type: application/json"`);
    // Escape single quotes so a body value containing an apostrophe (e.g. "O'Brien")
    // still produces a valid single-quoted shell argument.
    const body = JSON.stringify(input.requestBody).replace(/'/g, `'\\''`);
    lines.push(`  -d '${body}'`);
  } else {
    lines.push(tail);
  }
  // Join with backslash-continued newlines for shell readability.
  return lines
    .map((l, i) => (i < lines.length - 1 ? `${l} \\` : l))
    .join("\n");
}
