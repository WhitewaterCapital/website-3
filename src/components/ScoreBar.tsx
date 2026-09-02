// A -100..+100 diverging bar: red to the left (hostile), green to the right
// (supportive), centered at zero. Used for Distresse's dimension scorecard.
export function ScoreBar({ score }: { score: number }) {
  const clamped = Math.max(-100, Math.min(100, score));
  const half = Math.abs(clamped) / 2; // % width of the bar from center
  const positive = clamped >= 0;
  return (
    <div className="relative h-2 w-full rounded-full bg-foreground/10">
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
