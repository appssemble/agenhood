import { useEffect, useRef, useState } from "react";
import type { FileEntry } from "../api/types";
import { containerFileRawUrl } from "../api/fileUrls";
import { buildFileTree, type TreeNode } from "../lib/fileTree";
import { formatBytes } from "../lib/format";
import { Icons } from "../ui/Icon";
import { useDeleteFile } from "../api/queries";
import { useToast } from "./Toast";
import { ApiError } from "../api/client";
import { ConfirmDialog } from "./ConfirmDialog";

// --- Tree pane ---

interface TreeItemProps {
  cid: string;
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (node: TreeNode) => void;
  onRequestDelete: (node: TreeNode) => void;
  onUpload: (file: File, dir: string) => void;
}

function TreeItem({ cid, node, depth, selectedPath, onSelect, onRequestDelete, onUpload }: TreeItemProps) {
  const [open, setOpen] = useState(true);

  if (node.type === "file") {
    const isSelected = selectedPath === node.path;
    return (
      <div
        className={`row${isSelected ? " sel" : ""}`}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        role="button"
        tabIndex={0}
        onClick={() => onSelect(node)}
        onKeyDown={(e) => e.key === "Enter" && onSelect(node)}
      >
        <Icons.File />
        <span className="nm" title={node.name}>{node.name}</span>
        {node.size !== undefined && (
          <span className="sz">{formatBytes(node.size)}</span>
        )}
        <a
          href={containerFileRawUrl(cid, node.path)}
          aria-label={`Download ${node.name}`}
          className="btn btn-ghost btn-icon btn-sm"
          title="Download"
          onClick={(e) => e.stopPropagation()}
        >
          <Icons.Download w={12} />
        </a>
        <button
          type="button"
          aria-label={`Delete ${node.name}`}
          className="btn btn-ghost btn-icon btn-sm"
          title="Delete"
          onClick={(e) => {
            e.stopPropagation();
            onRequestDelete(node);
          }}
        >
          <Icons.Trash w={12} />
        </button>
      </div>
    );
  }

  const isSelected = selectedPath === node.path;
  const subFolders = node.children?.filter((c) => c.type === "folder") ?? [];
  const subFiles = node.children?.filter((c) => c.type === "file") ?? [];

  return (
    <div>
      <div
        className={`row${isSelected ? " sel" : ""}`}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        role="button"
        tabIndex={0}
        onClick={() => { setOpen((o) => !o); onSelect(node); }}
        onKeyDown={(e) => e.key === "Enter" && (setOpen((o) => !o), onSelect(node))}
      >
        <Icons.Folder />
        <span className="nm" title={node.name}>{node.name}</span>
        {(subFolders.length + subFiles.length) > 0 && (
          <span className="sz">{subFolders.length + subFiles.length}</span>
        )}
        <label
          className="btn btn-ghost btn-icon btn-sm"
          title="Upload to this folder"
          onClick={(e) => e.stopPropagation()}
        >
          <Icons.Upload w={12} />
          <input
            type="file"
            aria-label={`Upload to ${node.name}`}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f, node.path);
              e.target.value = "";
            }}
          />
        </label>
        <button
          type="button"
          aria-label={`Delete folder ${node.name}`}
          className="btn btn-ghost btn-icon btn-sm"
          title="Delete folder"
          onClick={(e) => {
            e.stopPropagation();
            onRequestDelete(node);
          }}
        >
          <Icons.Trash w={12} />
        </button>
      </div>
      {open && (
        <>
          {/* Folders first, then the folder's files — so the tree is the single
              place to browse and select files (no separate file-list column). */}
          {[...subFolders, ...subFiles].map((child) => (
            <TreeItem
              key={child.path}
              cid={cid}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              onRequestDelete={onRequestDelete}
              onUpload={onUpload}
            />
          ))}
        </>
      )}
    </div>
  );
}

// --- Preview pane ---

interface PreviewPaneProps {
  cid: string;
  node: TreeNode;
  onRequestDelete: (node: TreeNode) => void;
}

const TEXT_TYPES = ["text/", "application/json", "application/xml", "application/yaml"];
const MAX_PREVIEW_BYTES = 500_000;

// The /files/raw endpoint forwards the workspace file server's content-type,
// which defaults to application/octet-stream for most files — so a text/binary
// decision based solely on the header would mark every file binary. We also
// treat a known text extension as previewable, then confirm by decoding.
const TEXT_EXTENSIONS = new Set([
  "txt", "md", "markdown", "json", "csv", "tsv", "log", "xml", "yaml", "yml",
  "toml", "ini", "cfg", "conf", "env", "html", "htm", "css", "scss", "less",
  "js", "jsx", "ts", "tsx", "mjs", "cjs", "py", "rb", "go", "rs", "java", "kt",
  "c", "h", "cpp", "hpp", "cc", "sh", "bash", "zsh", "fish", "sql", "graphql",
  "vue", "svelte", "php", "pl", "lua", "r", "swift", "dockerfile", "gitignore",
]);

function isTextContentType(ct: string): boolean {
  return TEXT_TYPES.some((prefix) => ct.startsWith(prefix));
}

function hasTextExtension(name: string): boolean {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : name.toLowerCase();
  return TEXT_EXTENSIONS.has(ext);
}

// A file is previewable as text when either the server labels it text or its
// extension is a known text type (the octet-stream fallback case).
function looksLikeText(name: string, ct: string): boolean {
  return isTextContentType(ct) || hasTextExtension(name);
}

function PreviewPane({ cid, node, onRequestDelete }: PreviewPaneProps) {
  const [status, setStatus] = useState<"loading" | "text" | "binary" | "large" | "error">("loading");
  const [content, setContent] = useState<string>("");

  // The files API resolves the path relative to the workspace root, so send the
  // workspace-relative path the listing returned (NOT a leading-slash path — that
  // is treated as absolute by the server's path join and rejected as an escape).
  const href = containerFileRawUrl(cid, node.path);

  // Auto-load the preview whenever a different file is selected.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setContent("");
    const url = containerFileRawUrl(cid, node.path);
    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const ct = res.headers.get("content-type") ?? "";
        const size = node.size ?? 0;
        const isText = looksLikeText(node.name, ct);
        // A text file past the preview cap isn't binary — it's just too big to
        // render inline. Surface that distinctly so the message isn't misleading.
        if (isText && size >= MAX_PREVIEW_BYTES) {
          if (!cancelled) setStatus("large");
          return;
        }
        // Decode and confirm it really is text — a NUL byte means binary even
        // when the extension/content-type suggested otherwise.
        const text = isText ? await res.text() : null;
        if (cancelled) return;
        if (text !== null && !text.includes(String.fromCharCode(0))) {
          setContent(text);
          setStatus("text");
        } else {
          setStatus("binary");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [cid, node.name, node.path, node.size]);

  return (
    <div className="file-preview">
      <div className="head">
        <Icons.File />
        <div>
          <div className="nm">{node.name}</div>
          <div className="meta">
            {node.path.split("/").slice(0, -1).join("/") || "/"} · {node.size !== undefined ? formatBytes(node.size) : ""}
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-ghost btn-sm"
          >
            <Icons.Eye w={12} /> Raw
          </a>
          <a
            href={href}
            aria-label={`Download ${node.name}`}
            className="btn btn-secondary btn-sm"
          >
            <Icons.Download w={12} /> Download
          </a>
          <button
            type="button"
            aria-label={`Delete ${node.name}`}
            className="btn btn-ghost btn-sm"
            onClick={() => onRequestDelete(node)}
          >
            <Icons.Trash w={12} /> Delete
          </button>
        </div>
      </div>

      <div className="body">
        {status === "loading" && (
          <span style={{ color: "var(--muted)" }}>Loading preview…</span>
        )}
        {status === "error" && (
          <span style={{ color: "var(--muted)" }}>Failed to load preview.</span>
        )}
        {status === "binary" && (
          <span style={{ color: "var(--muted)" }}>Binary file. Download to view.</span>
        )}
        {status === "large" && (
          <span style={{ color: "var(--muted)" }}>
            File too large to preview (over {formatBytes(MAX_PREVIEW_BYTES)}). Download to view.
          </span>
        )}
        {status === "text" && content}
      </div>
    </div>
  );
}

// --- Main FileBrowser ---

interface FileBrowserProps {
  cid: string;
  files: FileEntry[];
  onUpload: (file: File, dir: string) => void;
}

// Persisted width (px) of the file-tree pane, clamped so neither pane collapses.
const TREE_WIDTH_KEY = "filebrowser.treeWidth";
const TREE_MIN = 180;
const TREE_MAX = 640;
const TREE_DEFAULT = 260;
const TREE_STEP = 24; // keyboard nudge per arrow press

function clampWidth(w: number): number {
  return Math.max(TREE_MIN, Math.min(TREE_MAX, w));
}

export function FileBrowser({ cid, files, onUpload }: FileBrowserProps) {
  const [selectedFile, setSelectedFile] = useState<TreeNode | null>(null);
  const [deleting, setDeleting] = useState<TreeNode | null>(null);
  const [treeWidth, setTreeWidth] = useState<number>(() => {
    const stored = Number(localStorage.getItem(TREE_WIDTH_KEY));
    return stored ? clampWidth(stored) : TREE_DEFAULT;
  });
  const containerRef = useRef<HTMLDivElement>(null);
  const del = useDeleteFile(cid);
  const toast = useToast();

  const tree = buildFileTree(files);
  const deletingFolder = deleting?.type === "folder";

  // Persist width whenever it settles.
  useEffect(() => {
    localStorage.setItem(TREE_WIDTH_KEY, String(treeWidth));
  }, [treeWidth]);

  // Drag the separator: translate the pointer's X into a tree-pane width
  // relative to the container's left edge.
  function startDrag(e: React.PointerEvent) {
    e.preventDefault();
    const left = containerRef.current?.getBoundingClientRect().left ?? 0;
    function onMove(ev: PointerEvent) {
      setTreeWidth(clampWidth(ev.clientX - left));
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    }
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function onSeparatorKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setTreeWidth((w) => clampWidth(w - TREE_STEP));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      setTreeWidth((w) => clampWidth(w + TREE_STEP));
    }
  }

  function handleTreeSelect(node: TreeNode) {
    if (node.type === "file") setSelectedFile(node);
  }

  async function confirmDelete() {
    const node = deleting;
    setDeleting(null);
    if (!node) return;
    try {
      await del.mutateAsync(node.path);
      toast.success(`Deleted ${node.name}`);
      // Drop the preview if the open file was deleted — either directly, or
      // because the folder it lived in was removed.
      setSelectedFile((cur) =>
        cur && (cur.path === node.path || cur.path.startsWith(`${node.path}/`)) ? null : cur,
      );
    } catch (err) {
      toast.error("Couldn't delete", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <>
      <div
        ref={containerRef}
        style={{
          display: "grid",
          gridTemplateColumns: `${treeWidth}px 6px 1fr`,
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
          borderTop: "1px solid var(--border)",
        }}
      >
        {/* Left: tree (folders + files) */}
        <div className="file-tree">
          {tree.length === 0 ? (
            <div style={{ padding: "10px 8px", fontSize: 13, color: "var(--muted)" }}>Empty</div>
          ) : (
            tree.map((node) => (
              <TreeItem
                key={node.path}
                cid={cid}
                node={node}
                depth={0}
                selectedPath={selectedFile?.path ?? null}
                onSelect={handleTreeSelect}
                onRequestDelete={setDeleting}
                onUpload={onUpload}
              />
            ))
          )}
        </div>

        {/* Draggable splitter: drag (pointer) or arrow-keys (keyboard) to give
            the tree more/less room. */}
        <div
          className="file-split-gutter"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize file tree"
          aria-valuemin={TREE_MIN}
          aria-valuemax={TREE_MAX}
          aria-valuenow={treeWidth}
          tabIndex={0}
          onPointerDown={startDrag}
          onKeyDown={onSeparatorKey}
        />

        {/* Right: preview */}
        {selectedFile ? (
          <PreviewPane
            key={selectedFile.path}
            cid={cid}
            node={selectedFile}
            onRequestDelete={setDeleting}
          />
        ) : (
          <div
            className="file-preview"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              color: "var(--muted)",
            }}
          >
            Select a file to preview
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!deleting}
        title={deletingFolder ? "Delete folder" : "Delete file"}
        body={
          deletingFolder
            ? `Delete "${deleting?.name}" and everything inside it? This cannot be undone.`
            : `Delete "${deleting?.name}"? This removes it from the workspace and cannot be undone.`
        }
        confirmLabel={deletingFolder ? "Delete folder" : "Delete file"}
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </>
  );
}
