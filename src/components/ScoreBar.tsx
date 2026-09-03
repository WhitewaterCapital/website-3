// A -100..+100 diverging bar: red to the left (hostile), green to the right
// (supportive), centered at zero. Used for Distresse's dimension scorecard.
//
// Color carries the hostile/supportive read, but never ALONE: `role="img"`
// + `aria-label` spell out the same read in words for screen readers, and the
// bar grows from a visible center tick rather than filling as a solid block,
// so direction is also legible as shape (which side of center, and how far)
// in greyscale or for a colorblind reader. Callers that already print the
// numeric score next to the bar (RankingsTable, Distresse's dimension list)
// satisfy the "not color-only" rule visually too.
export function ScoreBar({ score }: { score: number }) {
  const clamped = Math.max(-100, Math.min(100, score));
  const half = Math.abs(clamped) / 2; // % width of the bar from center
  const positive = clamped >= 0;
  const label =
    clamped === 0
      ? "Score 0 — neutral"
      : `Score ${clamped > 0 ? "+" : ""}${clamped.toFixed(0)} — ${positive ? "supportive" : "hostile"}`;
  return (
    <div
      className="relative h-2 w-full rounded-full bg-foreground/10"
      role="img"
      aria-label={label}
    >
      <div className="absolute left-1/2 top-0 h-full w-px bg-foreground/25" />
      <div
        className={`absolute top-0 h-full rounded-full ${
          positive ? "bg-emerald-500" : "bg-rose-500"
        }`}
        style={
          positive
            ? { left: "50%", width: `${half}%` }
            : { right: "50%", width: `${half}%` }
        }
      />
    </div>
  );
}
