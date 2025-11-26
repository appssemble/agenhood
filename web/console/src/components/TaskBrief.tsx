import { useState } from "react";
import { CopyButton } from "./CopyButton";

/**
 * The task prompt, in a dedicated bounded section so long text scrolls inside
 * its own box instead of pushing the rest of the screen down. Collapsible.
 */
export function TaskBrief({ prompt }: { prompt: string }) {
  const [open, setOpen] = useState(true);

  return (
    <section className={`task-brief ${open ? "expanded" : "collapsed"}`}>
      <div className="brief-head">
        <span className="lab">Task brief</span>
        <span className="spacer" />
        {open && <CopyButton text={prompt} />}
        <button
          className="mini-btn"
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={open ? "Hide task brief" : "Show task brief"}
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && <div className="brief-body">{prompt}</div>}
    </section>
  );
}
