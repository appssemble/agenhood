import { useRef } from "react";
import { driverLabel, driverDesc, driverIcon } from "../lib/drivers";

export function DriverPicker({
  value, drivers, onChange,
}: {
  value: string;
  drivers: string[];
  onChange: (driver: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  // Arrow keys move between cards and select, per the ARIA radio-group pattern.
  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const dir =
      e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 :
      e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const cur = Math.max(0, drivers.indexOf(value));
    const next = (cur + dir + drivers.length) % drivers.length;
    onChange(drivers[next]);
    refs.current[next]?.focus();
  }

  return (
    <div className="driver-grid" role="radiogroup" aria-label="Driver" onKeyDown={onKeyDown}>
      {drivers.map((d, i) => {
        const Glyph = driverIcon(d);
        const selected = d === value;
        return (
          <button
            key={d}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={driverLabel(d)}
            tabIndex={selected ? 0 : -1}
            className={`driver-card${selected ? " selected" : ""}`}
            onClick={() => onChange(d)}
          >
            <span className="driver-card-ico"><Glyph w={18} /></span>
            <span className="driver-card-name">{driverLabel(d)}</span>
            <span className="driver-card-desc">{driverDesc(d)}</span>
          </button>
        );
      })}
    </div>
  );
}
