import type { ReactNode } from "react";

/** Circular progress ring for a 0..1 ratio (e.g. success rate). The label
 *  goes in the center via children. Animates the arc on value change. */
export function Ring({
  percent,
  size = 78,
  stroke = 9,
  color = "var(--p-500)",
  track = "var(--surface-3)",
  children,
}: {
  percent: number | null;
  size?: number;
  stroke?: number;
  color?: string;
  track?: string;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = percent === null ? 0 : Math.max(0, Math.min(1, percent));
  const dash = c * pct;
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={track} strokeWidth={stroke} />
        {percent !== null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${c - dash}`}
            style={{ transition: "stroke-dasharray .6s cubic-bezier(.22,1,.36,1)" }}
          />
        )}
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>{children}</div>
    </div>
  );
}
