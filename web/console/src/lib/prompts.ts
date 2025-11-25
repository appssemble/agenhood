// Shared {{variable}} parsing/resolution for the prompt library, editor preview,
// and the picker. Mirrors the backend regex in prompts_service.py.
const VAR_RE = /\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g;

export function extractVariables(body: string): string[] {
  const seen: string[] = [];
  for (const m of (body ?? "").matchAll(VAR_RE)) {
    const name = m[1];
    if (!seen.includes(name)) seen.push(name);
  }
  return seen;
}

export function resolve(body: string, values: Record<string, string>): string {
  return (body ?? "").replace(VAR_RE, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) && values[name] !== ""
      ? values[name]
      : whole,
  );
}
