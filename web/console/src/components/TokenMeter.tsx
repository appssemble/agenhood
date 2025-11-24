export function TokenMeter({ used, cap }: { used: number; cap?: number | null }) {
  const pct = cap ? Math.min(100, Math.round((used / cap) * 100)) : null;
  const tone = pct == null ? "" : pct >= 90 ? "danger" : pct >= 75 ? "warn" : "";
  return (
    <div className={`meter${tone ? ` ${tone}` : ""}`}>
      <div className="row">
        <span><span className="used">{used.toLocaleString()}</span> tokens</span>
        {cap ? <span className="cap">/ {cap.toLocaleString()}</span> : null}
      </div>
      {cap ? (
        <div className="track">
          <div data-testid="meter-fill" className={`fill${tone ? ` ${tone}` : ""}`} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      {cap && pct != null ? (
        <div className="row">
          <span className="cap" />
          <span style={{ color: "var(--y-300)" }}>{pct}%</span>
        </div>
      ) : null}
    </div>
  );
}
