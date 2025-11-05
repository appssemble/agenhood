// Shared slug-name validation, mirroring the control plane's name checks:
// lowercase a-z / 0-9 with single hyphens, max 64 chars.
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** Returns an error message, or null when `name` is a valid slug (or empty).
 *  `example` is woven into the message (e.g. "git-release", "my-server"). */
export function slugNameError(name: string, example: string): string | null {
  if (!name) return null;
  if (name.length > 64 || !NAME_RE.test(name)) {
    return `Use lowercase a-z, 0-9 and single hyphens (e.g. ${example}).`;
  }
  return null;
}
