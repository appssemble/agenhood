/**
 * agenhood logomark — an "a / \" monogram.
 *
 * A single-story "a", a tall slash, and a smaller backslash whose foot sits on
 * the baseline beside the slash. The asymmetric pair (tall left, short right)
 * reads as an "h" — agen·hood. Monochrome by default (currentColor), matching
 * the rail's "a/" tile — ink on the yellow field. Pass `accent` to tint just
 * the slash + backslash.
 */
type Props = {
  /** Rendered height of the monogram in px. */
  size?: number;
  /** Optional colour for the slash + backslash. Defaults to currentColor (monochrome). */
  accent?: string;
  /** Show the "agenhood" wordmark beside the monogram. */
  withWordmark?: boolean;
  className?: string;
  /** Accessible name when the wordmark text isn't rendered. */
  title?: string;
};

export function Logo({
  size = 30,
  accent = "currentColor",
  withWordmark = false,
  className = "",
  title = "agenhood",
}: Props) {
  const w = (size * 44) / 32;
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: Math.round(size * 0.36) }}
    >
      <svg
        width={w}
        height={size}
        viewBox="0 0 44 32"
        fill="none"
        stroke="currentColor"
        strokeWidth={3.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        role={withWordmark ? undefined : "img"}
        aria-hidden={withWordmark ? true : undefined}
        aria-label={withWordmark ? undefined : title}
        focusable="false"
      >
        {/* a — single-story bowl + right stem */}
        <circle cx="10.9" cy="20.6" r="5.6" />
        <line x1="16.5" y1="14.6" x2="16.5" y2="26.6" />
        {/* the slash + a smaller backslash on the baseline — reads as "h".
            The /\ group sits a comfortable gap to the right of the a. */}
        <g stroke={accent}>
          <line x1="21.5" y1="27" x2="31.5" y2="5" />
          <line x1="32.5" y1="15" x2="38" y2="27" />
        </g>
      </svg>
      {withWordmark && (
        <span style={{ fontWeight: 800, fontSize: Math.round(size * 0.62), letterSpacing: "-0.02em" }}>
          agenhood
        </span>
      )}
    </span>
  );
}
