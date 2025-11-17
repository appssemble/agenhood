import { cx } from "../lib/cx";
export function SegControl<T extends string>({
  options, value, onChange, className = "",
}: {
  options: { value: T; label: React.ReactNode; disabled?: boolean }[];
  value: T; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div className={cx("seg", className)}>
      {options.map((o) => (
        <button key={o.value} type="button" disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={o.value === value ? "active" : ""}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
