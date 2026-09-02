// Dependency-free SVG line chart. Draws one or two series on a shared scale
// with a light grid. Used for the equity curve and the us-vs-SPY comparison.

type Series = {
  values: number[];
  color: string;
  label: string;
};

export function LineChart({
  series,
  labels,
  height = 260,
  yFormat = (v: number) => v.toFixed(0),
}: {
  series: Series[];
  labels: string[];
  height?: number;
  yFormat?: (v: number) => string;
}) {
  const width = 720;
  const padL = 48;
  const padR = 12;
  const padT = 12;
  const padB = 24;

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
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full min-w-[520px]"
        role="img"
        aria-label={series.map((s) => s.label).join(" vs ")}
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
          />
        ))}
      </svg>

      <div className="mt-2 flex gap-4 pl-12 text-xs text-foreground/60">
        {series.map((s, i) => (
          <span key={i} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-3 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
