import { ReactNode } from "react";
import Link from "next/link";

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
        <div className="mb-5 flex items-center justify-between border-b border-hairline pb-3">
          {title ? <h2 className="eyebrow">{title}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

// A live-status indicator: a pulsing dot (see globals.css .live-dot) paired
// with a text label — never color/motion alone. `stale` greys it out for data
// that's real but not from this session (a snapshot, a synthetic-demo export,
// or one past its own TTL) rather than pretending everything is equally live.
export function LiveDot({ stale = false, label }: { stale?: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted">
      <span className={`live-dot ${stale ? "stale" : ""}`} aria-hidden />
      {label}
    </span>
  );
}

// A dense status/summary tile for a strip of many small readouts (e.g. one
// per model on the dashboard) — deliberately smaller and more compact than
// `Card`, which is built for one focused block of content.
export function Tile({
  eyebrow,
  title,
  children,
  status,
  href,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  status?: ReactNode;
  href?: string;
}) {
  const body = (
    <div className="flex h-full flex-col border border-hairline bg-paper p-4 transition hover:border-foreground/30">
      <div className="flex items-start justify-between gap-2">
        <span className="eyebrow">{eyebrow}</span>
        {status}
      </div>
      <div className="mt-1.5 text-sm font-semibold text-foreground">{title}</div>
      {children ? <div className="mt-1.5 text-xs leading-relaxed text-muted">{children}</div> : null}
    </div>
  );
  if (href) {
    return (
      <Link href={href} className="block h-full">
        {body}
      </Link>
    );
  }
  return body;
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
