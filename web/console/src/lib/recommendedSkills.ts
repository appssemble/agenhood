// Client-side fetch of the curated "Awesome SKILL.md" catalog (skills.json),
// shown in the New skill screen's "Recommended" tab. Each catalog entry is a
// repository that contains one or more SKILL.md files; we expand those into
// individually installable skills (each pinned to its own subpath + branch).
// Installing reuses the normal git-import path (POST /v1/skills, source_type
// "git") with the skill's subpath and branch.

/** One installable skill = one SKILL.md inside a repo. */
export interface RecommendedSkill {
  /** Stable id: repo url + "#" + subpath. */
  id: string;
  /** "owner/repo" */
  repoName: string;
  url: string;
  branch: string;
  /** Directory containing SKILL.md, "" for the repo root. */
  subpath: string;
  /** Leaf folder name (or repo name for a root SKILL.md). */
  label: string;
}

export interface RecommendedRepo {
  /** Repo url, also the row id. */
  id: string;
  repoName: string;
  url: string;
  category: string;
  description: string;
  branch: string;
  skills: RecommendedSkill[];
}

const CATALOG_URL =
  "https://raw.githubusercontent.com/appssemble/awesome-skill-md/main/skills.json";

function dirOf(file: string): string {
  const i = file.lastIndexOf("/");
  return i === -1 ? "" : file.slice(0, i);
}

function leafOf(path: string, fallback: string): string {
  if (!path) return fallback;
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}

export async function fetchRecommendedSkills(): Promise<RecommendedRepo[]> {
  const res = await fetch(CATALOG_URL, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: unknown = await res.json();
  const raw = (data as { skills?: unknown })?.skills;
  if (!Array.isArray(raw)) throw new Error("unexpected catalog format");

  const repos: RecommendedRepo[] = [];
  for (const r of raw as Record<string, unknown>[]) {
    if (!r || typeof r.url !== "string" || typeof r.name !== "string") continue;
    const files = Array.isArray(r.skillFiles)
      ? (r.skillFiles as unknown[]).filter((f): f is string => typeof f === "string")
      : [];
    if (files.length === 0) continue; // no known SKILL.md path -> not installable

    const branch = typeof r.branch === "string" && r.branch ? r.branch : "main";
    const repoLeaf = typeof r.repo === "string" && r.repo ? r.repo : r.name;

    const seen = new Set<string>();
    const skills: RecommendedSkill[] = [];
    for (const f of files) {
      const subpath = dirOf(f);
      if (seen.has(subpath)) continue;
      seen.add(subpath);
      skills.push({
        id: `${r.url}#${subpath}`,
        repoName: r.name,
        url: r.url,
        branch,
        subpath,
        label: subpath ? leafOf(subpath, repoLeaf) : repoLeaf,
      });
    }
    if (skills.length === 0) continue;

    repos.push({
      id: r.url,
      repoName: r.name,
      url: r.url,
      category: (typeof r.category === "string" && r.category) || "Other",
      description: typeof r.description === "string" ? r.description : "",
      branch,
      skills,
    });
  }
  return repos;
}

export interface CatalogGroup {
  category: string;
  items: RecommendedRepo[];
}

/** Group repos by category, preserving first-seen category order. */
export function groupByCategory(repos: RecommendedRepo[]): CatalogGroup[] {
  const order: string[] = [];
  const byCategory = new Map<string, RecommendedRepo[]>();
  for (const repo of repos) {
    const list = byCategory.get(repo.category);
    if (list) {
      list.push(repo);
    } else {
      byCategory.set(repo.category, [repo]);
      order.push(repo.category);
    }
  }
  return order.map((category) => ({ category, items: byCategory.get(category)! }));
}
