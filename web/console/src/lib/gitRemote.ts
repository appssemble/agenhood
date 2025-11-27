// Mirror of the server-side SSH URL + branch validators (git_remotes_service.py).
const SCP = /^([^@/]+@)?([^/:]+):(.*)$/;
const HOST = /^[A-Za-z0-9.-]+$/;
// eslint-disable-next-line no-control-regex -- intentional: mirrors git check-ref-format control-char rules
const BRANCH_BAD = /[ \x00-\x1f\x7f~^:?*[\\]|\.\.|@\{|\/\//;

/** Returns an error message, or null when the URL is a valid SSH remote. */
export function validateSshUrl(url: string): string | null {
  const u = url.trim();
  if (!u) return "Enter an SSH URL";
  if (/^https?:\/\//.test(u)) return "Use an SSH URL, not http(s)";
  if (/:\/\//.test(u) && !u.startsWith("ssh://")) return "Use an SSH URL";
  if (u.startsWith("ssh://")) {
    const rest = u.slice("ssh://".length);
    const authority = rest.split("/", 1)[0];
    const userinfo = authority.includes("@") ? authority.slice(0, authority.lastIndexOf("@")) : "";
    if (userinfo && userinfo.includes(":")) return "Don't embed a password";
    const slash = rest.indexOf("/");
    const host = authority.slice(authority.lastIndexOf("@") + 1).split(":")[0];
    if (!host) return "Missing host";
    if (!HOST.test(host)) return "Host has invalid characters";
    if (slash < 0 || !rest.slice(slash + 1)) return "Missing repository path";
    return null;
  }
  const m = SCP.exec(u);
  if (!m) return "Use git@host:owner/repo";
  if ((m[1] ?? "").replace(/@$/, "").includes(":")) return "Don't embed a password";
  const host = m[2];
  if (!HOST.test(host)) return "Host has invalid characters";
  if (!m[3].trim()) return "Missing repository path";
  return null;
}

/** Returns an error message, or null when the branch name is valid. */
export function validateBranch(branch: string): string | null {
  const b = branch.trim();
  if (!b || b === "@") return "Enter a branch name";
  if (b.startsWith("/") || b.endsWith("/") || b.endsWith(".") || b.endsWith(".lock"))
    return "Invalid branch name";
  if (BRANCH_BAD.test(b)) return "Invalid branch name";
  if (b.length > 255) return "Branch name too long";
  return null;
}
