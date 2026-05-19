import { Pill } from "../../../ui/Pill";
import { Icons } from "../../../ui/Icon";
import { CopyId } from "../../../ui/CopyId";
import { shortId } from "../../../lib/format";
import { STEP_BADGE_COLOR, STEP_PILL_TONE, type PipelineStepVM } from "./derive";

function StepCard({
  vm, selected, onSelect,
}: { vm: PipelineStepVM; selected: boolean; onSelect: () => void }) {
  const badgeColor = vm.status ? STEP_BADGE_COLOR[vm.status] : "var(--border-strong)";
  // The card is a div[role="button"] (not a <button>) so it can legally contain
  // the CopyId <button> for the prompt id.
  return (
    <div
      role="button"
      tabIndex={0}
      className={`pstep ${selected ? "sel" : ""}`.trim()}
      aria-label={`Step ${vm.index + 1}: ${vm.promptName}`}
      aria-expanded={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); }
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
        <span
          style={{
            width: 22, height: 22, borderRadius: 7, background: badgeColor,
            color: "#fff", fontSize: 11, fontWeight: 800,
            display: "grid", placeItems: "center", flexShrink: 0,
          }}
        >
          {vm.status === "completed" ? <Icons.Check w={12} /> : vm.index + 1}
        </span>
        {vm.status && (
          <Pill tone={STEP_PILL_TONE[vm.status]}>
            {vm.status}
            {vm.durationLabel ? ` · ${vm.durationLabel}` : ""}
          </Pill>
        )}
      </div>
      <div title={vm.promptName} style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {vm.promptName}
      </div>
      {/* Short prompt id with a copy affordance; clicking it must not select the
          step, so swallow the bubbling click/keydown. */}
      <div
        style={{ marginBottom: 9 }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <CopyId id={vm.promptId} label={shortId(vm.promptId)} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span className="tag" style={{ fontSize: 10.5 }}>{vm.containerName}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--muted-2)" }}>
          {vm.varCount} {vm.varCount === 1 ? "var" : "vars"}
        </span>
      </div>
    </div>
  );
}

export function PipelineTrack({
  steps, selectedIndex, onSelect,
}: {
  steps: PipelineStepVM[];
  selectedIndex: number | null;
  onSelect: (i: number) => void;
}) {
  return (
    <div className="pipeline-wrap">
      <div className="pipeline-track">
        {steps.map((vm, i) => (
          <div key={vm.index} style={{ display: "flex" }}>
            <StepCard vm={vm} selected={selectedIndex === vm.index} onSelect={() => onSelect(vm.index)} />
            {i < steps.length - 1 && <div className="conn-h" aria-hidden />}
          </div>
        ))}
      </div>
      <div className="pipeline-fade" aria-hidden />
    </div>
  );
}
