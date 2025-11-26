import { buildFileTree } from "./fileTree";

test("nests files under folders from slash-delimited paths", () => {
  const tree = buildFileTree([
    { path: "README.md", size: 10 },
    { path: "reports/q3.md", size: 20 },
    { path: "reports/2026/jan.md", size: 30 },
  ]);
  const folders = tree.filter((n) => n.type === "folder").map((n) => n.name);
  expect(folders).toContain("reports");
  const reports = tree.find((n) => n.name === "reports")!;
  expect(reports.children!.some((c) => c.name === "2026" && c.type === "folder")).toBe(true);
});

test("renders an empty directory from an explicit is_dir entry", () => {
  const tree = buildFileTree([
    { path: "emptydir", size: 0, is_dir: true },
    { path: "notes.md", size: 5, is_dir: false },
  ]);
  const empty = tree.find((n) => n.name === "emptydir");
  expect(empty).toBeDefined();
  expect(empty!.type).toBe("folder");
  expect(empty!.children).toEqual([]);
});
