import { Icons } from "../ui/Icon";

export interface ChangedFile {
  path: string;
  op: string;
}

function opSymbol(op: string): string {
  if (op === "create") return "+";
  if (op === "delete") return "-";
  return "~";
}

/** Full-width list of files the agent changed, derived from file_changed events. */
export function FilesPanel({
  files,
  downloadHref,
}: {
  files: ChangedFile[];
  downloadHref: (path: string) => string;
}) {
  if (files.length === 0) {
    return (
      <div className="files-pane">
        <p className="result-empty">No files changed yet.</p>
      </div>
    );
  }

  return (
    <div className="files-pane">
      {files.map(({ path, op }) => {
        const name = path.split("/").pop() ?? path;
        const dir = path.slice(0, path.length - name.length);
        return (
          <div key={path} className="file-row">
            <span className={`op ${op}`} title={op}>{opSymbol(op)}</span>
            <span className="path">
              <span className="dir">{dir}</span>
              {name}
            </span>
            <a className="dl mini-btn" href={downloadHref(path)} aria-label={`Download ${name}`}>
              <Icons.Download w={12} /> Download
            </a>
          </div>
        );
      })}
    </div>
  );
}
