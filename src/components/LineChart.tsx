// Dependency-free SVG line chart. Draws one or more series on a shared scale
// with a light grid. Used for the equity curve and the us-vs-SPY comparison.
//
// IMP-02 polish: an optional y-axis label (so the numbers carry a unit, not
// just digits), a legend that only shows once there's more than one series to
// disambiguate, a shape difference (dashing) between series so color alone
// never carries the distinction, an honest "no data" panel instead of a blank
// chart, and an optional freshness line. `asOf`/`generatedAt` are two
// DIFFERENT timestamps (when the underlying data is current to vs. when this
// view was computed) — pass whichever you honestly have; never fabricate one.

type Series = {
  values: number[];
  color: string;
  label: string;
  /** Optional dash pattern override. Defaults: solid for the 1st series, a
   * short dash for every series after it, so shape (not just color)
   * distinguishes lines for colorblind readers and in greyscale print. */
  dash?: string;
};

export function LineChart({
  series,
  labels,
  height = 260,
  yFormat = (v: number) => v.toFixed(0),
  yAxisLabel,
  xAxisLabel,
  asOf,
  generatedAt,
}: {
  series: Series[];
  labels: string[];
  height?: number;
  yFormat?: (v: number) => string;
  /** What the y-axis measures, unit included, e.g. "Cumulative return (%)". */
  yAxisLabel?: string;
  /** What the x-axis measures, if not obvious from the tick labels themselves. */
  xAxisLabel?: string;
  /** The date/time the plotted DATA is current to. Shown honestly, not fabricated. */
  asOf?: string | null;
  /** The date/time this view was COMPUTED — a separate fact from `asOf`, never merged with it. */
  generatedAt?: string | null;
}) {
  const width = 720;
  const padL = 48;
  const padR = 12;
  const padT = yAxisLabel ? 26 : 12;
  const padB = 24;

  const hasData = labels.length > 0 && series.some((s) => s.values.length > 0);

  if (!hasData) {
    return (
      <div
        className="flex w-full items-center justify-center border border-dashed border-hairline text-sm text-muted"
        style={{ height }}
      >
        No data yet.
      </div>
    );
  }

  const all = series.flatMap((s) => s.values);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  // pad the range a touch so lines don't hug the edges
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;

  const n = labels.length;
  const x = (i: number) =>
    padL + (i / Math.max(1, n - 1)) * (width - padL - padR);
  const y = (v: number) =>
    padT + (1 - (v - yMin) / (yMax - yMin)) * (height - padT - padB);

  const path = (values: number[]) =>
    values
      .map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
      .join(" ");

  const gridLines = 4;
  const ticks = Array.from({ length: gridLines + 1 }, (_, i) => {
    const v = yMin + (i / gridLines) * (yMax - yMin);
    return { v, y: y(v) };
  });

  // show a handful of x labels
  const xTickIdx = Array.from({ length: Math.min(6, n) }, (_, i) =>
    Math.round((i / Math.max(1, Math.min(6, n) - 1)) * (n - 1)),
  );

  return (
    <div className="w-full">
      {yAxisLabel && (
        <p className="mb-1 pl-12 text-[10px] uppercase tracking-wide text-muted">
          {yAxisLabel}
        </p>
      )}
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full min-w-[520px]"
          role="img"
          aria-label={[yAxisLabel, series.map((s) => s.label).join(" vs ")]
            .filter(Boolean)
            .join(" — ")}
        >
          {ticks.map((t, i) => (
            <g key={i}>
              <line
                x1={padL}
                x2={width - padR}
                y1={t.y}
                y2={t.y}
                className="stroke-foreground/10"
                strokeWidth={1}
              />
              <text
                x={padL - 8}
                y={t.y + 3}
                textAnchor="end"
                className="fill-foreground/40"
                fontSize={10}
              >
                {yFormat(t.v)}
              </text>
            </g>
          ))}

          {xTickIdx.map((idx) => (
            <text
              key={idx}
              x={x(idx)}
              y={height - 6}
              textAnchor="middle"
              className="fill-foreground/40"
              fontSize={10}
            >
              {labels[idx]}
            </text>
          ))}

          {series.map((s, i) => (
            <path
              key={i}
              d={path(s.values)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={s.dash ?? (i === 0 ? undefined : "5,4")}
            />
          ))}
        </svg>
      </div>

      {xAxisLabel && (
        <p className="mt-1 pl-12 text-[10px] uppercase tracking-wide text-muted">
          {xAxisLabel}
        </p>
      )}

      {series.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-4 pl-12 text-xs text-foreground/60">
          {series.map((s, i) => (
            <span key={i} className="inline-flex items-center gap-1.5">
              <svg width="16" height="8" aria-hidden="true">
                <line
                  x1="0"
                  y1="4"
                  x2="16"
                  y2="4"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dash ?? (i === 0 ? undefined : "5,4")}
                />
              </svg>
              {s.label}
            </span>
          ))}
        </div>
      )}

      {(asOf || generatedAt) && (
        <p className="mt-2 pl-12 text-[11px] text-muted">
          {asOf ? <>Data as of {asOf}</> : null}
          {asOf && generatedAt ? " · " : null}
          {generatedAt ? <>Computed {generatedAt}</> : null}
        </p>
      )}
    </div>
  );
}
