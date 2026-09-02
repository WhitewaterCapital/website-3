import Link from "next/link";

// Minimal top bar for module sub-pages: brand, a "back to the Desk" link, and
// logout. Navigation between modules happens from the Desk launcher, not a
// crowded top nav.
export function ModuleNav({ crumb }: { crumb?: string }) {
  return (
    <header className="border-b border-hairline">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="text-sm font-semibold uppercase tracking-[0.18em]"
          >
            Whitewater
          </Link>
          {crumb ? (
            <span className="text-xs uppercase tracking-[0.12em] text-muted">
              / {crumb}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-4 text-xs uppercase tracking-[0.12em]">
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
