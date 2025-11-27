import type { FileEntry } from "../api/types";

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "folder";
  size?: number;
  children?: TreeNode[];
}

export function buildFileTree(files: Pick<FileEntry, "path" | "size" | "is_dir">[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", type: "folder", children: [] };
  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    let cur = root;
    parts.forEach((part, i) => {
      const isLeaf = i === parts.length - 1;
      const path = parts.slice(0, i + 1).join("/");
      let node = cur.children!.find((c) => c.name === part);
      if (!node) {
        // Only a leaf that the API marked as a real file becomes a file node;
        // leaf directory entries (is_dir) and intermediate segments are folders.
        node = isLeaf && !f.is_dir
          ? { name: part, path, type: "file", size: f.size }
          : { name: part, path, type: "folder", children: [] };
        cur.children!.push(node);
      }
      if (!isLeaf) cur = node;
    });
  }
  return root.children!;
}
