/**
 * Appssemble logomark — the brand tile (dark rounded square + white "A").
 *
 * Appssemble is the team behind agenhood; this mark is used to credit them.
 * Sourced from appssemble.com's favicon. The brand colours are intentionally
 * fixed (not currentColor) so the mark stays on-brand on any surface.
 */
type Props = {
  /** Rendered size (width = height) in px. */
  size?: number;
  className?: string;
  /** Accessible name. */
  title?: string;
};

export function AppssembleLogo({ size = 16, className, title = "Appssemble" }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label={title}
      focusable="false"
    >
      <rect width="32" height="32" rx="5.6" fill="#131415" />
      <path d="M19.2573 3.76562L11.7159 25.8137H6.58594L14.1274 3.76562H19.2573Z" fill="#fff" />
      <rect x="15.2344" y="21.4033" width="10.1802" height="4.40962" fill="#fff" />
    </svg>
  );
}
