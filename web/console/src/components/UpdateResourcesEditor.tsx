import { useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { Icons } from "../ui/Icon";
import { useUpdateResources } from "../api/queries";
import { useToast } from "./Toast";

/**
 * Inline memory/CPU editor, rendered expanded inside the overview Resources
 * card (no modal/portal). `onDone` collapses the card — called on cancel and
 * after a successful update.
 */
export function UpdateResourcesEditor({
  cid,
  currentMemLimit,
  currentCpus,
  onDone,
}: {
  cid: string;
  currentMemLimit: string;
  currentCpus: number;
  onDone: () => void;
}) {
  const update = useUpdateResources(cid);
  const toast = useToast();
  const [memLimit, setMemLimit] = useState(currentMemLimit);
  const [cpus, setCpus] = useState(String(currentCpus));

  useEffect(() => {
    setMemLimit(currentMemLimit);
    setCpus(String(currentCpus));
  }, [currentMemLimit, currentCpus]);

  const parsedCpus = Number(cpus);
  const canSubmit =
    !!memLimit.trim() && !Number.isNaN(parsedCpus) && parsedCpus > 0 && !update.isPending;

  async function submit() {
    if (!canSubmit) return;
    try {
      await update.mutateAsync({ mem_limit: memLimit.trim(), cpus: parsedCpus });
      toast.success("Resources updated", "The new limits are in effect.");
      onDone();
    } catch (e) {
      toast.error("Couldn't update resources", e instanceof Error ? e.message : undefined);
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      <label className="cw-label" htmlFor="res-mem">Memory</label>
      <input
        id="res-mem"
        className="cw-input"
        value={memLimit}
        onChange={(e) => setMemLimit(e.target.value)}
        placeholder="e.g. 2g"
      />
      <label className="cw-label" htmlFor="res-cpu" style={{ marginTop: 8, display: "block" }}>
        CPUs
      </label>
      <input
        id="res-cpu"
        className="cw-input"
        value={cpus}
        onChange={(e) => setCpus(e.target.value)}
        placeholder="e.g. 1.5"
      />

      <p className="cw-sub" style={{ marginTop: 12 }}>
        Applies immediately on a running container, no restart. A paused container
        resumes after updating; an archived one picks it up on next restore.
      </p>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Button variant="primary" size="sm" disabled={!canSubmit} onClick={submit}>
          {update.isPending ? (
            <><span className="cw-spin" aria-hidden="true" /> Updating…</>
          ) : (
            <>Update <Icons.ArrowRight w={14} /></>
          )}
        </Button>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
