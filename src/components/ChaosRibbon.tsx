// CHAOS RIBBON — VIS-01. A horizontal state band under a price-style line,
// colored by a discrete state label with intensity by a 0-1 index — the
// visual surface for CHAOS-01 (chaos-engine/), which detects a dislocating
// market and classifies it into calm / stressed / dislocated / cascade via
// an explicit hysteresis state machine (see chaos-engine/chaos/state.py's
// `run_state_machine` / `STATE_LEVELS`).
//
// NO real export seam exists yet: `src/lib/chaos.ts` / `getChaosExport()`
// has not been built by the chaos-engine work (confirmed: no
// `src/lib/chaos.ts` in this tree at the time this component was written).
// Rather than a dynamic import of a module that doesn't exist yet (which
// would fail typechecking), this component takes the chaos series as an
// explicit, documented PROP — `ChaosPoint[]` — so it can be wired to
// `getChaosExport()` with a one-line change the moment that seam lands. The
// one call site in src/app/visuals/page.tsx passes a clearly-labeled SAMPLE
// fixture today; swap that array for `getChaosExport()` there once available.
//
// State color = a fixed 4-step status ramp (never themed, never reused for
// anything else — see globals.css), always paired with the state's text
// name in the legend, the scrubber readout, and each segment's tooltip —
// never color alone. Reduced motion: nothing here animates continuously;
// the only moving part is the scrubber needle, which is repositioned by
// prop, not a CSS transition, so there is nothing for
// `prefers-reduced-motion` to suppress.

import { Badge } from "@/components/ui";

export type ChaosPoint = {
  state: string; // documented but NOT a strict union: an unrecognised label
  // still renders (grey, labeled with its own text) rather than
  // crashing or being silently dropped.
  index: number; // 0..1 chaos index — combined-component severity
  asOf: string; // ISO timestamp this reading is current to
};

const STATE_COLOR: Record<string, string> = {
  calm: "var(--viz-status-calm)",
  stressed: "var(--viz-status-stressed)",
  dislocated: "var(--viz-status-dislocated)",
  cascade: "var(--viz-status-cascade)",
};
const STATE_ORDER = ["calm", "stressed", "dislocated", "cascade"];

export function ChaosRibbon({
  points,
  priceSeries,
  currentIndex,
  height = 220,
  sample = false,
}: {
  points: ChaosPoint[];
  /** Optional price-style backdrop, 1:1 aligned with `points`. Omitted if the caller has none — never synthesized here. */
  priceSeries?: number[];
  /** Replay scrubber position into `points`; omit for a static (non-replay) render. */
  currentIndex?: number;
  height?: number;
  /** True when `points` is an illustrative SAMPLE fixture, not real engine output — renders the amber SAMPLE banner. */
  sample?: boolean;
}) {
  if (points.length === 0) {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">Not synced yet</p>
        <p className="mt-2 text-sm text-foreground/80">
          No CHAOS-01 export is wired in yet — <code>src/lib/chaos.ts</code>{" "}
          doesn&apos;t exist in this build. This panel will read{" "}
          <code>getChaosExport()</code> once that seam lands.
        </p>
      </div>
    );
  }

  const width = 760;
  const padL = 48;
  const padR = 12;
  const ribbonH = 46;
  const axisH = 22;
  const gap = priceSeries ? 8 : 0;
  const priceH = priceSeries ? Math.max(50, height - ribbonH - axisH - gap - 4) : 0;

  const n = points.length;
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (width - padL - padR);
  const segW = (width - padL - padR) / n;

  const priceY = (() => {
    if (!priceSeries || priceSeries.length === 0) return () => 0;
    const min = Math.min(...priceSeries);
    const max = Math.max(...priceSeries);
    const span = max - min || 1;
    return (v: number) => priceH - ((v - min) / span) * (priceH - 8) - 4;
  })();

  const ribbonY = 4 + priceH + gap;
  const cur = currentIndex != null ? Math.max(0, Math.min(n - 1, currentIndex)) : null;
  const curPoint = cur != null ? points[cur] : null;

  const xTickIdx = Array.from({ length: Math.min(5, n) }, (_, i) =>
    Math.round((i / Math.max(1, Math.min(5, n) - 1)) * (n - 1)),
  );

  return (
    <div className="space-y-3">
      {sample && (
        <div className="border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          ⚠ <strong>SAMPLE — illustrative fixture, not real CHAOS-01 output.</strong>{" "}
          Swap for <code>getChaosExport()</code> once the chaos-engine export
          seam is built.
        </div>
      )}

      <div className="w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${4 + priceH + gap + ribbonH + axisH}`}
          className="w-full min-w-[560px]"
          role="img"
          aria-label="Chaos state ribbon: calm, stressed, dislocated, or cascade over time"
        >
          {priceSeries && priceSeries.length > 1 && (
            <>
              <path
                d={priceSeries
                  .map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${(4 + priceY(v)).toFixed(1)}`)
                  .join(" ")}
                fill="none"
                stroke="currentColor"
                strokeOpacity={0.55}
                strokeWidth={1.5}
              />
              <text x={padL} y={12} fontSize={9} className="fill-foreground/40">
                Price (illustrative, indexed)
              </text>
            </>
          )}

          {/* Ribbon segments */}
          {points.map((p, i) => {
            const color = STATE_COLOR[p.state] ?? "var(--viz-grey)";
            const intensity = Math.max(0, Math.min(1, p.index));
            return (
              <rect
                key={i}
                x={x(i)}
                y={ribbonY}
                width={Math.max(1, segW)}
                height={ribbonH}
                fill={color}
                fillOpacity={0.25 + intensity * 0.65}
              >
                <title>
                  {p.asOf} · {p.state} · chaos index {intensity.toFixed(2)}
                </title>
              </rect>
            );
          })}
          <rect x={padL} y={ribbonY} width={width - padL - padR} height={ribbonH} fill="none" className="stroke-foreground/15" strokeWidth={1} />

          {/* Scrubber needle */}
          {cur != null && (
            <line
              x1={x(cur) + segW / 2}
              x2={x(cur) + segW / 2}
              y1={ribbonY - 4}
              y2={ribbonY + ribbonH + 4}
              stroke="currentColor"
              strokeWidth={2}
            />
          )}

          {xTickIdx.map((idx) => (
            <text
              key={idx}
              x={x(idx) + segW / 2}
              y={ribbonY + ribbonH + 16}
              textAnchor="middle"
              fontSize={9}
              className="fill-foreground/40"
            >
              {points[idx]?.asOf?.slice(0, 10)}
            </text>
          ))}
        </svg>
      </div>

      {/* Legend — state color + text, always shown (4 categorical states) */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-foreground/60">
        {STATE_ORDER.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 capitalize">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: STATE_COLOR[s] }} />
            {s}
          </span>
        ))}
        <span className="text-[11px] text-muted">Intensity = chaos index (0–1)</span>
      </div>

      {curPoint && (
        <p className="text-xs text-foreground/80">
          <Badge tone="neutral">{curPoint.state}</Badge>{" "}
          <span className="ml-2 tabular-nums">index {curPoint.index.toFixed(2)}</span>{" "}
          <span className="ml-2 text-muted">{curPoint.asOf}</span>
        </p>
      )}

      <p className="text-[11px] text-muted">
        Data as of {points[points.length - 1].asOf}
      </p>
    </div>
  );
}
