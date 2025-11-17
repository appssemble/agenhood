import { useState } from "react";
import { Icons } from "./Icon";
import { copyText } from "../lib/clipboard";

// Small monospace id chip with a copy button. Shows "Copied" for ~1.5s after a
// successful copy. The displayed text may be a short `label` (or the id itself,
// visually truncated), but the FULL id is always copied.
export function CopyId({ id, label }: { id: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    if (await copyText(id)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  return (
    <button
      type="button"
      className="btn btn-secondary btn-sm"
      aria-label={`Copy prompt id ${id}`}
      title={id}
      onClick={onCopy}
      style={{ gap: 5, fontSize: 11, maxWidth: 220 }}
    >
      {copied ? <Icons.Check w={12} /> : <Icons.Copy w={12} />}
      <span
        style={{
          fontFamily: "var(--mono, ui-monospace, monospace)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {copied ? "Copied" : (label ?? id)}
      </span>
    </button>
  );
}
