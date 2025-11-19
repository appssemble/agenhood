/** Tiny inline area+line chart for at-a-glance trends inside stat tiles.
 *  Stretches to the container width; pass the raw series values. */
export function Sparkline({
  values,
  height = 38,
  stroke = "var(--p-500)",
  fill = "rgba(229,221,23,.16)",
  strokeWidth = 2,
}: {
  values: number[];
  height?: number;
  stroke?: string;
  fill?: string;
  strokeWidth?: number;
}) {
  const W = 100; // viewBox width; SVG scales to the container
  if (values.length === 0) return null;
  const max = Math.max(...values);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const n = values.length;
  const pts = values.map((v, i) => {
    const x = n > 1 ? (i / (n - 1)) * W : W / 2;
    const y = height - ((v - min) / range) * (height - strokeWidth) - strokeWidth / 2;
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${line} L${W},${height} L0,${height} Z`;
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      aria-hidden
      style={{ display: "block", overflow: "visible" }}
    >
      <path d={area} fill={fill} stroke="none" />
      <path
        d={line}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
