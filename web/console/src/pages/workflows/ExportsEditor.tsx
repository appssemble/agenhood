import { useState } from "react";
import { Icons } from "../../ui/Icon";

const MAX_EXPORTS = 20;
const MAX_EXPORT_LEN = 512;
const RESERVED_DIRS = [".agent-runtime", ".agent-state", ".git"];

/** Client-side mirror of the API's export-path rules so mistakes surface at
 *  add-time instead of as a 400 on save. Returns an error message or null. */
export function exportPathError(raw: string, existing: string[]): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (existing.length >= MAX_EXPORTS) return `A step can share at most ${MAX_EXPORTS} paths.`;
  if (v.length > MAX_EXPORT_LEN) return `Path is too long (max ${MAX_EXPORT_LEN} characters).`;
  if (v.startsWith("/")) return "Use a workspace-relative path — no leading /.";
  if (v.split("/").includes("..")) return "Paths can't contain ‘..’ segments.";
  if (RESERVED_DIRS.includes(v.split("/")[0])) return "Agent-internal folders and .git can't be shared.";
  if (existing.includes(v)) return "Already in the list.";
  return null;
}

interface ExportsEditorProps {
  stepIndex: number;
  isLast: boolean;
  exports: string[];
  onChange: (next: string[]) => void;
}

/** "Files to pass to next step" chip editor on a workflow builder step.
 *  Paths render as mono tags (they're workspace paths/globs); one add-input
 *  with inline validation replaces per-row inputs. */
export default function ExportsEditor({ stepIndex, isLast, exports: paths, onChange }: ExportsEditorProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const hintId = `step-${stepIndex}-exports-hint`;
  const errorId = `step-${stepIndex}-exports-error`;

  function add() {
    const v = draft.trim();
    if (!v) return;
    const err = exportPathError(v, paths);
    if (err) {
      setError(err);
      return;
    }
    onChange([...paths, v]);
    setDraft("");
    setError(null);
  }

  function remove(i: number) {
    onChange(paths.filter((_, idx) => idx !== i));
  }

  return (
    <div className="wfb-exports">
      <div className="wfb-vars-lab">
        Files to pass to next step
        {paths.length > 0 && <span className="wfb-exports-count">{paths.length}</span>}
      </div>

      {paths.length > 0 && (
        <ul className="wfb-exports-list" aria-label="Files to pass to next step">
          {paths.map((p, i) => (
            <li key={p} className="tag wfb-exports-tag" title={p}>
              <Icons.File w={12} />
              <span className="wfb-exports-path">{p}</span>
              <button
                type="button"
                className="wfb-exports-remove"
                aria-label={`Remove export ${i + 1}`}
                title={`Stop sharing ${p}`}
                onClick={() => remove(i)}
              >
                <Icons.Close w={11} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="wfb-exports-addrow">
        <input
          className="input"
          aria-label="Add export path"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : hintId}
          value={draft}
          placeholder="report.pdf or dist/**"
          onChange={(e) => {
            setDraft(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={add}
          disabled={!draft.trim()}
        >
          <Icons.Plus w={13} /> Add file
        </button>
      </div>

      {error ? (
        <div id={errorId} className="wfb-exports-error" role="alert">{error}</div>
      ) : (
        <div id={hintId} className="wfb-exports-hint">
          {paths.length === 0
            ? "Nothing shared yet — matched files are copied into the next step's workspace when this step finishes."
            : "Globs like dist/** match when the step finishes; a pattern with no matches fails the run."}
        </div>
      )}

      {isLast && paths.length > 0 && (
        <div className="note amber wfb-exports-lastnote">
          <Icons.Warn w={13} />
          <span>This is the <b>last step</b> — these files go nowhere until a step follows it.</span>
        </div>
      )}
    </div>
  );
}
