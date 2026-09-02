import { ReactNode } from "react";

// A labelled figure with an optional sub-line and up/down tone.
export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "up" | "down" | "neutral";
}) {
  const toneClass =
    tone === "up"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "down"
        ? "text-rose-600 dark:text-rose-400"
        : "text-foreground";
  return (
    <div className="border-t border-foreground/80 pt-3">
      <div className="eyebrow">{label}</div>
      <div className={`mt-2 text-3xl font-semibold tracking-tight tabular-nums ${toneClass}`}>
        {value}
      </div>
      {sub ? <div className="mt-1 text-xs text-muted">{sub}</div> : null}
    </div>
  );
}

export function Card({
  title,
  children,
  action,
}: {
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="border border-hairline bg-paper p-6">
      {(title || action) && (
        <div className="mb-5 flex items-center justify-between">
          {title ? <h2 className="eyebrow">{title}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "up" | "down" | "neutral" | "warn";
}) {
  const map = {
    up: "border-emerald-600/40 text-emerald-700 dark:text-emerald-400",
    down: "border-rose-600/40 text-rose-700 dark:text-rose-400",
    warn: "border-amber-600/40 text-amber-700 dark:text-amber-400",
    neutral: "border-foreground/25 text-muted",
  } as const;
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${map[tone]}`}
    >
      {children}
    </span>
  );
}
