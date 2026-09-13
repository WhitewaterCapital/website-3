import Link from "next/link";
import { LiveDot } from "@/components/ui";

// Top bar for module sub-pages: brand, a "back to the Desk" link, and logout.
// Navigation between modules happens from the Desk launcher, not a crowded
// top nav. Densified 2026-09-13 as part of the site-wide professional
// redesign — a thin accent rule under the bar plus a live-session indicator,
// in place of the previous plain hairline-only bar.
export function ModuleNav({ crumb }: { crumb?: string }) {
  return (
    <header className="border-b border-hairline bg-paper/60" style={{ borderBottomColor: "var(--accent)", borderBottomWidth: 2 }}>
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="font-mono text-sm font-semibold uppercase tracking-[0.18em] text-foreground"
          >
            Whitewater
          </Link>
          {crumb ? (
            <span className="text-xs uppercase tracking-[0.12em] text-muted">
              / {crumb}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-5 text-xs uppercase tracking-[0.12em]">
          <LiveDot label="Session live" />
          <Link href="/dashboard" className="text-muted hover:text-foreground">
            ← Desk
          </Link>
          <form action="/api/logout" method="post">
            <button className="border border-foreground/25 px-3 py-1 text-muted hover:border-foreground/50 hover:text-foreground">
              Log out
            </button>
          </form>
        </div>
      </div>
    </header>
  );
}
