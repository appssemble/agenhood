// Validators for a skill's git source, mirroring the control plane's checks
// (skills_fetch._validate_url — https:// only). Kept out of the SkillEditor
// component module so that file exports only its component (React Fast Refresh
// requires component-only exports; a stray helper export forces full reloads).

/** Returns an error message, or null when the URL is a valid https git URL. */
export function urlError(url: string): string | null {
  if (!url) return null;
  if (!/^https:\/\/\S+$/.test(url)) return "Enter an https:// git URL.";
  return null;
}

/** Display form of a git source URL: strips the scheme and a trailing .git. */
export function repoLabel(url?: string | null): string {
  if (!url) return "";
  return url.replace(/^https?:\/\//, "").replace(/\.git$/, "");
}
