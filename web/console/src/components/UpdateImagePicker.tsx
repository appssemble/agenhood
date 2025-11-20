import { useEffect, useMemo, useState } from "react";
import { Button } from "../ui/Button";
import { Icons } from "../ui/Icon";
import { useImageTags, useUpdateImage } from "../api/queries";
import { useToast } from "./Toast";

const CUSTOM = "__custom__";

/**
 * Inline image-tag picker, rendered expanded inside the overview Image card
 * (no modal/portal). `onDone` collapses the card — called on cancel and after
 * a successful update.
 */
export function UpdateImagePicker({
  cid,
  currentTag,
  onDone,
}: {
  cid: string;
  currentTag: string;
  onDone: () => void;
}) {
  const tagsQuery = useImageTags();
  const update = useUpdateImage(cid);
  const toast = useToast();
  const [selected, setSelected] = useState(currentTag);
  const [customTag, setCustomTag] = useState("");

  // Reset the selection when the target container/tag changes.
  useEffect(() => {
    setSelected(currentTag);
    setCustomTag("");
  }, [currentTag]);

  const data = tagsQuery.data;
  const registryTags = useMemo(
    () => (data?.tags ?? []).filter((t) => t.source === "registry"),
    [data],
  );
  const localTags = useMemo(
    () => (data?.tags ?? []).filter((t) => t.source === "local"),
    [data],
  );

  const resolvedTag = selected === CUSTOM ? customTag.trim() : selected;
  const canSubmit = !!resolvedTag && !update.isPending;

  async function submit() {
    if (!canSubmit) return;
    try {
      await update.mutateAsync(resolvedTag);
      toast.success(`Updating to "${resolvedTag}"`, "The container will recreate on the new image.");
      onDone();
    } catch (e) {
      toast.error("Couldn't update image", e instanceof Error ? e.message : undefined);
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      <label className="cw-label" htmlFor="img-tag">
        Image tag
      </label>
      <select
        id="img-tag"
        className="cw-input"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
      >
        {registryTags.length > 0 && (
          <optgroup label="Registry">
            {registryTags.map((t) => (
              <option key={`r-${t.tag}`} value={t.tag}>
                {t.tag}
                {t.tag === currentTag ? " (current)" : ""}
                {t.tag === data?.default_tag ? " — default" : ""}
              </option>
            ))}
          </optgroup>
        )}
        {localTags.length > 0 && (
          <optgroup label="Local / dev">
            {localTags.map((t) => (
              <option key={`l-${t.tag}`} value={t.tag}>
                {t.tag}
                {t.tag === currentTag ? " (current)" : ""}
              </option>
            ))}
          </optgroup>
        )}
        <option value={CUSTOM}>Custom…</option>
      </select>

      {selected === CUSTOM && (
        <input
          className="cw-input"
          style={{ marginTop: 8 }}
          autoFocus
          placeholder="e.g. dev-myfeature"
          value={customTag}
          onChange={(e) => setCustomTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
      )}

      {data?.registry_unavailable && (
        <p className="cw-sub" style={{ marginTop: 8 }}>
          Registry unreachable — showing local images only. You can still enter a tag manually.
        </p>
      )}

      <p className="cw-sub" style={{ marginTop: 12 }}>
        Updating briefly recreates the container and interrupts any running task.
      </p>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Button variant="primary" size="sm" disabled={!canSubmit} onClick={submit}>
          {update.isPending ? (
            <>
              <span className="cw-spin" aria-hidden="true" /> Updating…
            </>
          ) : (
            <>
              Update <Icons.ArrowRight w={14} />
            </>
          )}
        </Button>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
