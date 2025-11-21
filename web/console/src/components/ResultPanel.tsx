import { Icons } from "../ui/Icon";
import { CopyButton } from "./CopyButton";

interface ResultLike {
  success?: boolean;
  output?: unknown;
  files?: string[];
  reason?: string | null;
}

/** Render the task output as readable text — pretty-print objects/JSON, leave strings as-is. */
function formatOutput(output: unknown): string {
  if (typeof output === "string") return output;
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return String(output);
  }
}

/**
 * Full-width result view. Long output wraps and scrolls with the pane (no narrow
 * rail), so large outputs stay readable. Lists any files the result produced.
 */
export function ResultPanel({
  result,
  terminal,
  downloadHref,
}: {
  result: ResultLike | null | undefined;
  terminal: boolean;
  downloadHref: (path: string) => string;
}) {
  const hasOutput = result?.output != null && formatOutput(result.output).length > 0;
  const text = hasOutput ? formatOutput(result!.output) : "";

  return (
    <div className="result-pane">
      <div className="result-head">
        <h3>Result</h3>
        {terminal && result?.success != null && (
          <span className={`pill ${result.success ? "pill-success" : "pill-error"}`}>
            <span className="dot" />
            {result.success ? "success" : "failed"}
          </span>
        )}
        <span className="spacer" />
        {hasOutput && <CopyButton text={text} label="Copy output" />}
      </div>

      {hasOutput ? (
        <pre className="result-output">{text}</pre>
      ) : (
        <p className="result-empty">
          {terminal
            ? "This task produced no textual output."
            : "Updates as the agent writes. The final result appears here on completion."}
        </p>
      )}

      {result?.reason && (
        <p className="result-empty" style={{ marginTop: 12 }}>{result.reason}</p>
      )}

      {result?.files && result.files.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="head" style={{ fontSize: 10.5, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700, marginBottom: 8 }}>
            Result files
          </div>
          {result.files.map((f) => (
            <div key={f} className="file-row">
              <Icons.File w={14} />
              <span className="path">{f}</span>
              <a className="dl mini-btn" href={downloadHref(f)} aria-label={`Download ${f}`}>
                <Icons.Download w={12} /> {f.split("/").pop()}
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
