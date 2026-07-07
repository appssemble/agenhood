import { useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { Dropdown } from "../ui/Dropdown";
import { Icons } from "../ui/Icon";
import { useUpdateResources } from "../api/queries";
import { MEM_OPTIONS, CPU_OPTIONS, withCurrentValue } from "../lib/resourceOptions";
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

  // Values only ever come from the fixed dropdown lists (or the pre-filled
  // current value), both always valid, so there's nothing left to validate.
  const canSubmit = !update.isPending;
  const memOptions = withCurrentValue(MEM_OPTIONS, currentMemLimit);
  const cpuOptions = withCurrentValue(CPU_OPTIONS, String(currentCpus));

  async function submit() {
    if (!canSubmit) return;
    try {
      const result = await update.mutateAsync({ mem_limit: memLimit, cpus: Number(cpus) });
      if (result.applied) {
        toast.success("Resources updated", "The new limits are in effect.");
      } else {
        toast.success("Resources saved", "They'll apply the next time this container is restored.");
      }
      onDone();
    } catch (e) {
      toast.error("Couldn't update resources", e instanceof Error ? e.message : undefined);
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      <label className="cw-label" htmlFor="res-mem">Memory</label>
      <Dropdown id="res-mem" value={memLimit} onChange={setMemLimit} options={memOptions} />
      <label className="cw-label" htmlFor="res-cpu" style={{ marginTop: 8, display: "block" }}>
        CPUs
      </label>
      <Dropdown id="res-cpu" value={cpus} onChange={setCpus} options={cpuOptions} />

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
