import { useSearchParams } from "react-router-dom";
import { SegControl } from "../ui/SegControl";
import { RANGES, isRange, type Range } from "../lib/range";

export function useRange(): Range {
  const [params] = useSearchParams();
  const v = params.get("range");
  return isRange(v) ? v : "7d";
}

export function RangeToggle() {
  const [params, setParams] = useSearchParams();
  const current = useRange();
  const onChange = (r: Range) => {
    const next = new URLSearchParams(params);
    next.set("range", r);
    setParams(next, { replace: true });
  };
  return (
    <SegControl<Range>
      options={RANGES.map((r) => ({ value: r, label: r }))}
      value={current}
      onChange={onChange}
    />
  );
}
