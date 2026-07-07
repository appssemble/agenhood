// Validators for a skill's git source, mirroring the control plane's checks
// (skills_fetch._validate_url — https:// only, or ssh when a deploy key is
// attached). Kept out of the SkillEditor component module so that file exports
// only its component (React Fast Refresh requires component-only exports; a
// stray helper export forces full reloads).
import { validateSshUrl } from "./gitRemote";

/** Error message for a skill's git source URL, or null when valid/empty.
 *  Without a deploy key the control plane requires https; with one, ssh. */
export function sourceUrlError(url: string, hasKey: boolean): string | null {
  if (!url) return null;
  if (hasKey) {
    return validateSshUrl(url) ? "Enter an ssh URL (git@github.com:org/repo.git)." : null;
  }
  if (!/^https:\/\/\S+$/.test(url)) return "Enter an https:// git URL.";
  return null;
}

/** Display form of a git source URL: strips the scheme and a trailing .git. */
export function repoLabel(url?: string | null): string {
  if (!url) return "";
  return url.replace(/^https?:\/\//, "").replace(/\.git$/, "");
}
