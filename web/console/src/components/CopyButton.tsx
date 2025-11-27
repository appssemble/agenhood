import { useState } from "react";
import { Icons } from "../ui/Icon";
import { copyText } from "../lib/clipboard";

/** Small ghost "copy to clipboard" button used in the task brief and result heads. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);

  async function copy() {
    if (await copyText(text)) {
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    }
  }

  return (
    <button className="mini-btn" onClick={copy} type="button" aria-label={label}>
      {done ? <Icons.Check w={12} /> : <Icons.Copy w={12} />}
      {done ? "Copied" : label}
    </button>
  );
}
