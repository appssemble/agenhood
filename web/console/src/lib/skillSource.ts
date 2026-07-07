// Validators for a skill's git source, mirroring the control plane's checks
// (skills_fetch._validate_url — https:// only, or ssh when a deploy key is
// attached). Kept out of the SkillEditor component module so that file exports
// only its component (React Fast Refresh requires component-only exports; a
// stray helper export forces full reloads).
import { validateSshUrl } from "./gitRemote";

/** Error message for a skill's git source URL, or null when valid/empty.
 *  Without a deploy key the control plane requires https; with one, ssh.
 *  Callers should validate the NORMALIZED url (normalizeSourceUrl) so users
 *  can paste either form and never hit a wrong-scheme error. */
export function sourceUrlError(url: string, hasKey: boolean): string | null {
  if (!url) return null;
  if (hasKey) {
    return validateSshUrl(url) ? "Enter a repository URL (https://github.com/org/repo or git@github.com:org/repo.git)." : null;
  }
  if (!/^https:\/\/\S+$/.test(url)) return "Enter a repository URL (https://github.com/org/repo).";
  return null;
}

// https://host/owner/repo(.git)  |  git@host:owner/repo(.git)  |  ssh://git@host/owner/repo(.git)
const _HTTPS_RE = /^https:\/\/([A-Za-z0-9.-]+)\/(\S+?)(?:\.git)?\/?$/;
const _SCP_RE = /^(?:[A-Za-z0-9._-]+@)([A-Za-z0-9.-]+):(\S+?)(?:\.git)?$/;
const _SSH_RE = /^ssh:\/\/(?:[A-Za-z0-9._-]+@)?([A-Za-z0-9.-]+)(?::\d+)?\/(\S+?)(?:\.git)?$/;

/** Convert a pasted repo URL to the scheme the control plane requires:
 *  ssh (git@host:path.git) when a deploy key is attached, https otherwise.
 *  Users paste whatever they copied — usually the browser's https URL — and
 *  never see a wrong-scheme error. Unparseable input is returned unchanged
 *  (sourceUrlError then reports it). */
export function normalizeSourceUrl(url: string, hasKey: boolean): string {
  const u = url.trim();
  if (!u) return u;
  if (hasKey) {
    const m = _HTTPS_RE.exec(u);
    return m ? `git@${m[1]}:${m[2]}.git` : u;
  }
  const m = _SCP_RE.exec(u) ?? _SSH_RE.exec(u);
  return m ? `https://${m[1]}/${m[2]}` : u;
}

/** Display form of a git source URL: strips the scheme and a trailing .git. */
export function repoLabel(url?: string | null): string {
  if (!url) return "";
  return url.replace(/^https?:\/\//, "").replace(/\.git$/, "");
}
