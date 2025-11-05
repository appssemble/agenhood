/** Join truthy className parts with single spaces, collapsing any internal
 *  whitespace. Falsy parts (""/false/null/undefined) are dropped. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}
