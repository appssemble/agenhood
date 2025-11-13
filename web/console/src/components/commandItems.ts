import type { Container, Template } from "../api/types";

export type CommandItem =
  | { kind: "container"; id: string; label: string; sub: string; to: string }
  | { kind: "template"; id: string; label: string; sub: string; to: string }
  | { kind: "action"; label: string; sub: string; to: string };

export function buildItems(containers: Container[], templates: Template[]): CommandItem[] {
  return [
    ...containers.map((c): CommandItem => ({
      kind: "container", id: c.id, label: c.name,
      sub: `${c.external_id ?? c.id} · ${c.status}`, to: `/containers/${c.id}`,
    })),
    ...templates.map((t): CommandItem => ({
      kind: "template", id: t.id, label: t.name,
      sub: `template · ${t.driver}`, to: `/settings/templates`,
    })),
    { kind: "action", label: "Dashboard", sub: "fleet overview", to: "/" },
    { kind: "action", label: "Tasks", sub: "activity across the fleet", to: "/tasks" },
    { kind: "action", label: "New container", sub: "from a template", to: "/containers/new" },
    { kind: "action", label: "Templates", sub: "browse & clone", to: "/settings/templates" },
  ];
}

export function filterItems(items: CommandItem[], q: string): CommandItem[] {
  const s = q.trim().toLowerCase();
  if (!s) return items;
  return items.filter((i) => i.label.toLowerCase().includes(s) || i.sub.toLowerCase().includes(s));
}
