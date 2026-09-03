// CASCADE NETWORK — VIS-01. Fund products as hubs, their constituents as
// leaves, edge width = holding weight. A replay scrubber steps through a
// sample "session" of a flow shock at one hub propagating pressure outward —
// the WW-CASCADE mechanism (quant-infra/cascade/): "pressure scales with the
// weight the name carries... where a name sits in several products, sum
// across all of them" (quant-infra/cascade/pressure.py).
//
// NO real ETF holdings/flow data exists anywhere in this sandbox (confirmed:
// no holdings ingestion, no DATA-01 pipeline). Everything drawn here —
// the fund list, the constituent weights, and the propagation session — is a
// clearly-labeled SAMPLE fixture, not a real cascade read. Wiring this to
// real names requires the holdings-ingestion work (DATA-01) plus a
// `getCascadeExport()`-style seam this repo does not have yet.
//
// Layout is a fixed, deterministic radial arrangement (hubs in a row,
// leaves arranged under the hub(s) that hold them) rather than a physics
// force-simulation — this app has no bundled graph-layout library and no
// network access to add one, and a deterministic layout is what a static +
// replay demo needs anyway (see VIS-01's own build order: static, then
// replay, before anything live). Pressure severity uses a single sequential
// hue (opacity-ramped) and is ALWAYS paired with a numeric readout — never
// color alone — both on hover and in the "highest pressure now" list below.

export type CascadeHolding = {
  fund: string;
  constituent: string;
  /** Portfolio weight, 0..1 (a signed short sleeve could be negative — not modeled in this sample). */
  weight: number;
};

export type CascadeStep = {
  /** Node id (fund name or ticker) -> pressure, 0..1. */
  pressureByNode: Record<string, number>;
};

const SAMPLE_HOLDINGS: CascadeHolding[] = [
  { fund: "Sample ETF Alpha", constituent: "AAPL", weight: 0.22 },
  { fund: "Sample ETF Alpha", constituent: "MSFT", weight: 0.18 },
  { fund: "Sample ETF Alpha", constituent: "NVDA", weight: 0.15 },
  { fund: "Sample ETF Alpha", constituent: "XOM", weight: 0.09 },
  { fund: "Sample ETF Beta", constituent: "AAPL", weight: 0.12 },
  { fund: "Sample ETF Beta", constituent: "JPM", weight: 0.2 },
  { fund: "Sample ETF Beta", constituent: "GS", weight: 0.14 },
  { fund: "Sample ETF Beta", constituent: "XOM", weight: 0.11 },
  { fund: "Sample ETF Gamma", constituent: "NVDA", weight: 0.25 },
  { fund: "Sample ETF Gamma", constituent: "MSFT", weight: 0.1 },
  { fund: "Sample ETF Gamma", constituent: "TLT", weight: 0.3 },
];

// Deterministic diffusion session — no randomness. A shock lands at
// `sourceFund` at step 0 (pressure 1.0) and diffuses across the
// fund<->constituent graph, peaking then decaying, so a name held by
// several funds visibly accumulates pressure from all of them (per the
// doc's "sum across all products holding the name").
function buildSampleSession(
  holdings: CascadeHolding[],
  sourceFund: string,
  totalSteps = 16,
): CascadeStep[] {
  const nodes = new Set<string>();
  holdings.forEach((h) => {
    nodes.add(h.fund);
    nodes.add(h.constituent);
  });
  const neighbors: Record<string, { id: string; w: number }[]> = {};
  nodes.forEach((n) => (neighbors[n] = []));
  holdings.forEach((h) => {
    neighbors[h.fund].push({ id: h.constituent, w: h.weight });
    neighbors[h.constituent].push({ id: h.fund, w: h.weight });
  });

  let pressure: Record<string, number> = {};
  nodes.forEach((n) => (pressure[n] = 0));
  pressure[sourceFund] = 1;
  const steps: CascadeStep[] = [{ pressureByNode: { ...pressure } }];

  for (let t = 1; t < totalSteps; t++) {
    const next: Record<string, number> = {};
    const decay = t > totalSteps * 0.4 ? 0.82 : 1;
    for (const n of nodes) {
      const inflow = neighbors[n].reduce((s, nb) => s + nb.w * pressure[nb.id], 0);
      next[n] = Math.min(1, (pressure[n] * 0.35 + inflow * 0.9) * decay);
    }
    pressure = next;
    steps.push({ pressureByNode: { ...pressure } });
  }
  return steps;
}

export function CascadeNetwork({
  holdings = SAMPLE_HOLDINGS,
  currentStep = 0,
  height = 420,
}: {
  holdings?: CascadeHolding[];
  /** Replay scrubber position into the propagation session. */
  currentStep?: number;
  height?: number;
}) {
  // Small, fixed-size fixture — recomputed per render rather than memoized,
  // so this component carries no hooks and can render on the server too.
  const funds = Array.from(new Set(holdings.map((h) => h.fund)));
  const constituents = Array.from(new Set(holdings.map((h) => h.constituent)));
  const sourceFund = funds[0];
  const session = buildSampleSession(holdings, sourceFund);
  const step = session[Math.max(0, Math.min(session.length - 1, currentStep))];

  if (holdings.length === 0) {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">No holdings data</p>
        <p className="mt-2 text-sm text-foreground/80">
          Live cascade data requires ETF holdings ingestion (DATA-01), which
          hasn&apos;t been built.
        </p>
      </div>
    );
  }

  const width = 760;
  const hubY = 64;
  const leafY = height - 70;
  const hubX = (i: number) => ((i + 1) / (funds.length + 1)) * width;
  const leafX = (i: number) => ((i + 1) / (constituents.length + 1)) * width;
  const pos: Record<string, { x: number; y: number; hub: boolean }> = {};
  funds.forEach((f, i) => (pos[f] = { x: hubX(i), y: hubY, hub: true }));
  constituents.forEach((c, i) => (pos[c] = { x: leafX(i), y: leafY, hub: false }));

  const maxWeight = Math.max(...holdings.map((h) => h.weight));
  const pressureOf = (id: string) => Math.max(0, Math.min(1, step.pressureByNode[id] ?? 0));

  const topPressure = Object.entries(step.pressureByNode)
    .filter(([, v]) => v > 0.02)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return (
    <div className="space-y-3">
      <div className="border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
        ⚠ <strong>SAMPLE — illustrative fixture, not real holdings.</strong> No
        ETF holdings data exists in this sandbox; live cascade data requires
        holdings ingestion (DATA-01) that hasn&apos;t been built.
      </div>

      <div className="w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full min-w-[560px]"
          role="img"
          aria-label="Sample cascade network: fund hubs, constituent leaves, edge width by holding weight, color by propagating pressure"
        >
          {/* Edges: width = holding weight (static), color intensity = pressure at this replay step */}
          {holdings.map((h, i) => {
            const a = pos[h.fund];
            const b = pos[h.constituent];
            const edgePressure = Math.max(pressureOf(h.fund), pressureOf(h.constituent));
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="var(--viz-status-cascade)"
                strokeOpacity={0.15 + edgePressure * 0.7}
                strokeWidth={1 + (h.weight / maxWeight) * 6}
              >
                <title>
                  {h.fund} → {h.constituent} · weight {(h.weight * 100).toFixed(0)}%
                </title>
              </line>
            );
          })}

          {/* Constituent (leaf) nodes */}
          {constituents.map((c) => {
            const p = pos[c];
            const pr = pressureOf(c);
            return (
              <g key={c}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={10}
                  fill="var(--viz-status-cascade)"
                  fillOpacity={0.15 + pr * 0.75}
                  stroke="currentColor"
                  strokeOpacity={0.3}
                >
                  <title>
                    {c} · pressure {pr.toFixed(2)}
                  </title>
                </circle>
                <text x={p.x} y={p.y + 24} textAnchor="middle" fontSize={10} className="fill-foreground/70">
                  {c}
                </text>
                {pr > 0.3 && (
                  <text x={p.x} y={p.y + 3} textAnchor="middle" fontSize={8} className="fill-foreground font-semibold">
                    {pr.toFixed(1)}
                  </text>
                )}
              </g>
            );
          })}

          {/* Fund (hub) nodes */}
          {funds.map((f) => {
            const p = pos[f];
            const pr = pressureOf(f);
            return (
              <g key={f}>
                <rect
                  x={p.x - 46}
                  y={p.y - 18}
                  width={92}
                  height={36}
                  rx={6}
                  fill="var(--viz-status-cascade)"
                  fillOpacity={0.15 + pr * 0.75}
                  stroke="currentColor"
                  strokeOpacity={0.4}
                >
                  <title>
                    {f} · pressure {pr.toFixed(2)}
                    {f === sourceFund ? " · shock origin" : ""}
                  </title>
                </rect>
                <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize={10} className="fill-foreground font-medium">
                  {f.replace("Sample ETF ", "")}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-foreground/60">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "var(--viz-status-cascade)", opacity: 0.85 }} />
          Fill opacity = mechanical pressure now (0–1)
        </span>
        <span>Edge width = holding weight (fixed, not animated)</span>
        <span>Step {currentStep + 1} / {session.length}</span>
      </div>

      {topPressure.length > 0 && (
        <p className="text-xs text-muted">
          Highest pressure right now: {topPressure.map(([id, v]) => `${id} (${v.toFixed(2)})`).join(", ")}
        </p>
      )}
    </div>
  );
}
