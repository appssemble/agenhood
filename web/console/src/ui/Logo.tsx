import { useId } from "react";

/**
 * agenhood logomark — the two-circle brand mark.
 *
 * A filled disc on the left and an open ring on the right; the disc carries a
 * curved gap where the ring overlaps it, so the pair reads as a linked "a·o".
 * This is the same mark used on agenhood.com's favicon. Monochrome by default
 * (currentColor) so it inherits the surrounding tile's ink — black on the
 * yellow rail / login tiles. Pass `accent` to tint just the ring.
 */
type Props = {
  /** Rendered height of the monogram in px. */
  size?: number;
  /** Optional colour for the ring. Defaults to currentColor (monochrome). */
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
  // useId() embeds colons (":r0:"); strip them so the id is safe in url(#…).
  const maskId = `logo-gap-${useId().replace(/:/g, "")}`;
  // The mark's natural frame is 155×110 (see favicon.svg): disc at (44,55) r44,
  // ring at (100,55) r44. Height drives `size`; width keeps the aspect ratio.
  const w = Math.round((size * 155) / 110);
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: Math.round(size * 0.36) }}
    >
      <svg
        width={w}
        height={size}
        viewBox="0 0 155 110"
        fill="none"
        role={withWordmark ? undefined : "img"}
        aria-hidden={withWordmark ? true : undefined}
        aria-label={withWordmark ? undefined : title}
        focusable="false"
      >
        <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="155" height="110">
          <rect x="0" y="0" width="155" height="110" fill="#fff" />
          {/* carve the gap where the ring crosses the disc */}
          <circle cx="100" cy="55" r="44" fill="none" stroke="#000" strokeWidth="36" />
        </mask>
        {/* a — filled disc, gapped by the mask */}
        <circle cx="44" cy="55" r="44" fill="currentColor" mask={`url(#${maskId})`} />
        {/* o — open ring, optionally accented */}
        <circle cx="100" cy="55" r="44" fill="none" stroke={accent} strokeWidth="22" />
      </svg>
      {withWordmark && (
        <span style={{ fontWeight: 800, fontSize: Math.round(size * 0.62), letterSpacing: "-0.02em" }}>
          agenhood
        </span>
      )}
    </span>
  );
}
