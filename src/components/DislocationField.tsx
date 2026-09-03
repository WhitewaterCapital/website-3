// DISLOCATION FIELD — VIS-01. A scatter of WW-GRAPH's residual dislocation
// (x: residual z-score vs. the graph-implied neighbourhood value) against its
// predicted reversion speed (y: half-life in days, ONLY when the engine found
// a statistically significant reversion — see graph-engine/ge/reversion.py).
//
// REAL data: fed entirely from `getGraphExport()` (public/data/graph/latest.json).
// This is genuinely computed, synthetic-DEMO market data (`data_provenance`
// is surfaced below, never hidden) — not fabricated for this chart.
//
// Quadrant read (an interpretive framing of the two real fields above, spelled
// out here since the export contract itself has no notion of "quadrants"):
//   x < 0 & significant reversion  -> "Left behind and expected to recover"
//   x > 0 & significant reversion  -> "Run ahead and expected to fade"
//   |x| small (within ±0.5)        -> "Moving with its peers"
//   |x| large & NOT significant    -> "Moving against the model" (diverged,
//                                      but the engine found no evidence it
//                                      reverts — shown in its own top band,
//                                      not merged into the numeric half-life
//                                      axis, since there is no real half-life
//                                      number for these).
// Names with `confidence: "insufficient"` (no residual computed at all) are
// NOT placeable on either axis — abstention must be visible, never hidden —
// so they're listed, greyed, in a separate strip below the chart instead of
// being dropped or forced onto axes with fabricated coordinates.
//
// Color = sector, one of 6 fixed slots (validated categorical palette, see
// globals.css). Six series exceed the all-pairs-safe cap of three the
// palette carries, so sector also gets a distinct MARKER SHAPE as a
// secondary channel, plus a text-labeled legend — color is never the only
// signal. Point size is uniform: no liquidity proxy exists in this export.
// Sector itself is derived from the synthetic universe's own ticker naming
// convention (`S{sector}N{name}`, see graph-engine/ge/synthetic.py) — there
// is no explicit sector field in the export contract yet.

import type { GraphExport, GraphResidual } from "@/lib/models/graph-export";
import { Badge } from "@/components/ui";

const SECTOR_COLORS = [
  "var(--viz-cat-1)",
  "var(--viz-cat-2)",
  "var(--viz-cat-3)",
  "var(--viz-cat-4)",
  "var(--viz-cat-5)",
  "var(--viz-cat-6)",
];

// One distinct SVG symbol per sector slot — the secondary (non-color) channel.
function Marker({ shape, color, x, y, r = 5 }: { shape: number; color: string; x: number; y: number; r?: number }) {
  const props = { fill: color, fillOpacity: 0.85, stroke: color, strokeWidth: 1 };
  switch (shape % 6) {
    case 0: // circle
      return <circle cx={x} cy={y} r={r} {...props} />;
    case 1: // square
      return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} {...props} />;
    case 2: // triangle
      return (
        <polygon
          points={`${x},${y - r * 1.15} ${x - r} ,${y + r * 0.85} ${x + r},${y + r * 0.85}`}
          {...props}
        />
      );
    case 3: // diamond
      return (
        <polygon
          points={`${x},${y - r * 1.2} ${x + r * 1.2},${y} ${x},${y + r * 1.2} ${x - r * 1.2},${y}`}
          {...props}
        />
      );
    case 4: // plus
      return (
        <g stroke={color} strokeWidth={2.2} strokeLinecap="round">
          <line x1={x - r} y1={y} x2={x + r} y2={y} />
          <line x1={x} y1={y - r} x2={x} y2={y + r} />
        </g>
      );
    default: // star (5-point, simplified as two overlaid triangles)
      return (
        <g {...props}>
          <polygon points={`${x},${y - r * 1.2} ${x - r} ,${y + r * 0.7} ${x + r},${y + r * 0.7}`} />
          <polygon points={`${x},${y + r * 1.2} ${x - r},${y - r * 0.7} ${x + r},${y - r * 0.7}`} />
        </g>
      );
  }
}

function sectorOf(ticker: string): { name: string; idx: number } {
  const m = /^S(\d+)N\d+$/.exec(ticker);
  if (!m) return { name: "Unknown sector", idx: SECTOR_COLORS.length }; // future/real tickers without this convention
  const idx = Number(m[1]) % SECTOR_COLORS.length;
  return { name: `Sector ${m[1]}`, idx };
}

export function DislocationField({ data }: { data: GraphExport | null }) {
  if (!data) {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">Not synced yet</p>
        <p className="mt-2 text-sm text-foreground/80">
          The WW-GRAPH engine hasn&apos;t exported. Run{" "}
          <code>python -m ge.export</code> in <code>graph-engine/</code> to
          populate <code>public/data/graph/latest.json</code>.
        </p>
      </div>
    );
  }

  if (data.residuals.length === 0) {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">No residuals this run</p>
        <p className="mt-2 text-sm text-foreground/80">
          The engine ran but the universe was empty — an honest empty result.
        </p>
      </div>
    );
  }

  const placeable = data.residuals.filter(
    (r): r is GraphResidual & { residual_z: number } =>
      r.confidence !== "insufficient" && r.residual_z != null,
  );
  const abstained = data.residuals.filter(
    (r) => r.confidence === "insufficient" || r.residual_z == null,
  );

  const width = 760;
  const height = 460;
  const padL = 56;
  const padR = 16;
  const padT = 20;
  const padB = 44;
  const topBandH = 56; // "moving against the model" band, above the numeric half-life axis

  const maxAbsZ = Math.max(1, ...placeable.map((r) => Math.abs(r.residual_z))) * 1.15;
  const maxHalfLife =
    Math.max(1, ...placeable.filter((r) => r.half_life_significant && r.half_life_days != null).map((r) => r.half_life_days as number)) * 1.15;

  const plotH = height - padT - padB - topBandH;
  const x = (z: number) => padL + ((z + maxAbsZ) / (2 * maxAbsZ)) * (width - padL - padR);
  // main region: half-life 0 (fast) at the BOTTOM, growing upward, so "closer to reverting now" reads low.
  const yMain = (hl: number) => padT + topBandH + plotH - (hl / maxHalfLife) * plotH;
  const yTopBand = padT + topBandH * 0.5; // fixed row for "no significant reversion" points

  const NEAR_ZERO = 0.5; // interpretive threshold for "moving with its peers" — documented above

  // Deterministic (non-random) horizontal jitter within the top band so
  // same-ticker points never collide, without resorting to Math.random().
  const jitter = (ticker: string) => {
    let h = 0;
    for (let i = 0; i < ticker.length; i++) h = (h * 31 + ticker.charCodeAt(i)) >>> 0;
    return ((h % 100) / 100 - 0.5) * (topBandH * 0.5);
  };

  const dividerY = padT + topBandH;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={data.data_provenance === "live" ? "up" : "warn"}>
          {data.data_provenance === "live" ? "Live market data" : "Synthetic demo data"}
        </Badge>
        <span className="text-xs text-muted">
          {data.data_provenance === "live"
            ? "Real, live-priced graph residuals."
            : "This engine's current output on this sandbox — not a real market read."}
        </span>
      </div>
      <p className="text-xs leading-relaxed text-muted">{data.disclaimer}</p>

      <div className="w-full overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[560px]" role="img" aria-label="Residual z-score vs. predicted reversion half-life, by sector">
          {/* Quadrant backgrounds */}
          <rect x={padL} y={padT} width={x(-NEAR_ZERO) - padL} height={topBandH} fill="var(--viz-status-dislocated)" fillOpacity={0.07} />
          <rect x={x(NEAR_ZERO)} y={padT} width={width - padR - x(NEAR_ZERO)} height={topBandH} fill="var(--viz-status-dislocated)" fillOpacity={0.07} />
          <rect x={padL} y={dividerY} width={x(-NEAR_ZERO) - padL} height={plotH} fill="var(--viz-cat-3)" fillOpacity={0.06} />
          <rect x={x(NEAR_ZERO)} y={dividerY} width={width - padR - x(NEAR_ZERO)} height={plotH} fill="var(--viz-cat-2)" fillOpacity={0.06} />
          <rect x={x(-NEAR_ZERO)} y={padT} width={x(NEAR_ZERO) - x(-NEAR_ZERO)} height={topBandH + plotH} fill="currentColor" fillOpacity={0.03} />

          {/* Divider between the numeric half-life axis and the "no significant reversion" band */}
          <line x1={padL} x2={width - padR} y1={dividerY} y2={dividerY} strokeDasharray="4,4" className="stroke-foreground/25" strokeWidth={1} />
          {/* Zero line */}
          <line x1={x(0)} x2={x(0)} y1={padT} y2={padT + topBandH + plotH} className="stroke-foreground/20" strokeWidth={1} />

          {/* Quadrant labels — plain words, exactly as specified */}
          <text x={padL + 6} y={padT + 12} fontSize={10} className="fill-foreground/50">Moving against the model</text>
          <text x={width - padR - 6} y={padT + 12} textAnchor="end" fontSize={10} className="fill-foreground/50">Moving against the model</text>
          <text x={padL + 6} y={dividerY + 14} fontSize={10} className="fill-foreground/50">Left behind and expected to recover</text>
          <text x={width - padR - 6} y={dividerY + 14} textAnchor="end" fontSize={10} className="fill-foreground/50">Run ahead and expected to fade</text>
          <text x={x(0)} y={height - padB + 16} textAnchor="middle" fontSize={10} className="fill-foreground/50">Moving with its peers</text>

          {/* Y axis ticks (half-life, days) */}
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const hl = f * maxHalfLife;
            return (
              <text key={f} x={padL - 8} y={yMain(hl) + 3} textAnchor="end" fontSize={9} className="fill-foreground/40">
                {hl.toFixed(1)}d
              </text>
            );
          })}
          {/* X axis ticks (residual z-score) */}
          {[-1, -0.5, 0, 0.5, 1].map((f) => {
            const z = f * maxAbsZ;
            return (
              <text key={f} x={x(z)} y={height - padB + 32} textAnchor="middle" fontSize={9} className="fill-foreground/40">
                {z >= 0 ? "+" : ""}
                {z.toFixed(1)}σ
              </text>
            );
          })}

          {/* Points */}
          {placeable.map((r) => {
            const { name, idx } = sectorOf(r.ticker);
            const color = SECTOR_COLORS[idx] ?? "var(--viz-grey)";
            const px = x(r.residual_z);
            const py =
              r.half_life_significant && r.half_life_days != null
                ? yMain(r.half_life_days)
                : yTopBand + jitter(r.ticker);
            return (
              <g key={r.ticker}>
                <title>
                  {r.ticker} · {name} · residual z {r.residual_z.toFixed(2)}
                  {r.half_life_significant && r.half_life_days != null
                    ? ` · half-life ${r.half_life_days.toFixed(1)}d`
                    : " · no significant reversion"}
                </title>
                <Marker shape={idx} color={color} x={px} y={py} />
              </g>
            );
          })}

          {/* Axis titles */}
          <text x={(padL + width - padR) / 2} y={height - 4} textAnchor="middle" fontSize={10} className="fill-foreground/60">
            Residual z-score (graph-implied divergence from peers)
          </text>
          <text
            x={14}
            y={dividerY + plotH / 2}
            textAnchor="middle"
            fontSize={10}
            className="fill-foreground/60"
            transform={`rotate(-90 14 ${dividerY + plotH / 2})`}
          >
            Predicted reversion half-life (days, when significant)
          </text>
        </svg>
      </div>

      {/* Sector legend — color AND shape AND text, never color alone */}
      <div className="flex flex-wrap gap-4 text-xs text-foreground/60">
        {Array.from(new Set(placeable.map((r) => sectorOf(r.ticker).idx)))
          .sort((a, b) => a - b)
          .map((idx) => (
            <span key={idx} className="inline-flex items-center gap-1.5">
              <svg width="14" height="14" aria-hidden="true">
                <Marker shape={idx} color={SECTOR_COLORS[idx] ?? "var(--viz-grey)"} x={7} y={7} r={5} />
              </svg>
              Sector {idx}
            </span>
          ))}
      </div>

      {abstained.length > 0 && (
        <div className="border border-dashed border-hairline p-3">
          <p className="eyebrow">
            Abstained — {abstained.length} name{abstained.length === 1 ? "" : "s"} with insufficient data
          </p>
          <p className="mt-1 text-xs text-muted">
            No residual could be computed for these names this run. Shown, not
            hidden, per the desk&apos;s abstention policy — they cannot be
            placed on either axis honestly.
          </p>
          <p className="mt-2 text-xs text-foreground/70">
            {abstained.map((r) => r.ticker).join(", ")}
          </p>
        </div>
      )}

      <p className="font-mono text-[11px] text-muted">
        WW-GRAPH {data.schema_version} · engine {data.engine_version} · data as
        of {data.as_of} · computed {data.generated_at} · {placeable.length}/
        {data.residuals.length} plotted
      </p>
    </div>
  );
}
