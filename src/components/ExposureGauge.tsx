// A half-circle dial showing how much of the pool is invested vs. in cash.
// This is the "how much is in trades" view that's safe to show publicly —
// it reveals exposure, never which positions.

export function ExposureGauge({
  investedPct,
  size = 200,
}: {
  investedPct: number;
  size?: number;
}) {
  const clamped = Math.max(0, Math.min(100, investedPct));
  const r = size / 2 - 14;
  const cx = size / 2;
  const cy = size / 2;

  // background arc (cash) + foreground arc (invested)
  const arc = (fromPct: number, toPct: number) => {
    const a0 = Math.PI + (fromPct / 100) * Math.PI;
    const a1 = Math.PI + (toPct / 100) * Math.PI;
    const p0 = { x: cx + r * Math.cos(a0), y: cy + r * Math.sin(a0) };
    const p1 = { x: cx + r * Math.cos(a1), y: cy + r * Math.sin(a1) };
    // A half-gauge never sweeps more than 180°, so the large-arc flag is always 0.
    return `M ${p0.x} ${p0.y} A ${r} ${r} 0 0 1 ${p1.x} ${p1.y}`;
  };

  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size / 2 + 16}`} className="w-full max-w-[240px]">
        <path
          d={arc(0, 100)}
          fill="none"
          strokeWidth={14}
          strokeLinecap="round"
          className="stroke-foreground/10"
        />
        <path
          d={arc(0, clamped)}
          fill="none"
          strokeWidth={14}
          strokeLinecap="round"
          stroke="currentColor"
        />
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          className="fill-foreground font-semibold"
          fontSize={26}
        >
          {clamped.toFixed(0)}%
        </text>
        <text
          x={cx}
          y={cy + 16}
          textAnchor="middle"
          className="fill-foreground/50"
          fontSize={11}
        >
          invested
        </text>
      </svg>
      <div className="mt-1 flex gap-4 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 bg-foreground" />
          In trades {clamped.toFixed(0)}%
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 bg-foreground/20" />
          Cash {(100 - clamped).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
