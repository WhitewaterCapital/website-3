import Link from "next/link";
import { LineChart } from "@/components/LineChart";
import { ExposureGauge } from "@/components/ExposureGauge";
import { HeroChart } from "@/components/HeroChart";
import { NewsletterSignup } from "@/components/NewsletterSignup";
import { Stat, Card } from "@/components/ui";
import { snapshots, members } from "@/lib/sample-data";
import { computeMetrics } from "@/lib/metrics";
import { pct, shortDate } from "@/lib/format";

// PUBLIC HOME PAGE — the shopfront.
// Track record + who we are. Deliberately NO tickers, positions, or holdings —
// only aggregate value, return, and exposure. Nothing here is copyable.
export default function PublicPage() {
  const m = computeMetrics(snapshots);
  const labels = snapshots.map((s) => shortDate(s.date));
  // Cumulative % increase from inception (indexed series start at 100).
  const usPct = m.portIndexed.map((v) => v - 100);
  const spyPct = m.spyIndexed.map((v) => v - 100);

  return (
    <div>
      {/* Transparent header overlaying the gradient hero */}
      <header className="absolute inset-x-0 top-0 z-10">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5 text-white">
          <span className="text-sm font-semibold uppercase tracking-[0.18em]">
            Whitewater
          </span>
          <nav className="flex items-center gap-6 text-xs uppercase tracking-[0.12em] text-white/80">
            <a href="#approach" className="hidden hover:text-white sm:inline">
              Approach
            </a>
            <a href="#track-record" className="hidden hover:text-white sm:inline">
              Track Record
            </a>
            <Link href="/invest" className="hover:text-white">
              Invest
            </Link>
            <Link
              href="/dashboard"
              className="rounded-full border border-white/40 px-4 py-1.5 hover:border-white"
            >
              Members
            </Link>
          </nav>
        </div>
      </header>

      {/* HERO */}
      <section className="mesh relative overflow-hidden text-white">
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[300px] text-white/40">
          <HeroChart values={m.portIndexed} />
        </div>
        <div className="relative mx-auto max-w-5xl px-6 pb-24 pt-24 sm:pb-32 sm:pt-36">
          <p className="rise rise-1 font-mono text-sm text-white/80">
            // A concentrated, conviction-led investment club.
          </p>
          <h1 className="rise rise-2 display mt-6 max-w-3xl text-5xl text-white sm:text-7xl">
            Sustained
            <br />
            <span className="pl-[0.15em] sm:pl-16">conviction in</span>
            <br />
            public markets.
          </h1>
          <p className="rise rise-3 mt-8 max-w-xl text-lg text-white/85">
            Five partners, one pooled book, one scorecard — measured against the
            benchmark that matters: the S&amp;P 500.
          </p>
          <div className="rise rise-4 mt-10 flex flex-wrap items-center gap-4">
            <Link
              href="/dashboard"
              className="group inline-flex items-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-medium text-neutral-900 transition hover:bg-white/90"
            >
              Members portal
              <span className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5">
                ↘
              </span>
            </Link>
            <a
              href="#track-record"
              className="inline-flex items-center gap-2 text-sm font-medium text-white underline decoration-white/40 underline-offset-4 hover:decoration-white"
            >
              See the track record →
            </a>
          </div>
        </div>
      </section>

      {/* STATS BAND */}
      <section className="border-b border-hairline">
        <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 px-6 py-12 sm:grid-cols-4">
          <Stat
            label="Total Return"
            value={pct(m.portReturn)}
            tone={m.portReturn >= 0 ? "up" : "down"}
            sub="since inception"
          />
          <Stat
            label="vs SPY"
            value={pct(m.alpha)}
            tone={m.alpha >= 0 ? "up" : "down"}
            sub={`SPY ${pct(m.spyReturn)}`}
          />
          <Stat
            label="Max Drawdown"
            value={pct(-m.maxDrawdown)}
            tone="down"
            sub="worst peak-to-trough"
          />
          <Stat label="Partners" value={members.length} sub="one pooled account" />
        </div>
      </section>

      {/* APPROACH */}
      <section id="approach" className="border-b border-hairline">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="font-mono text-sm text-accent">// The Approach</p>
          <h2 className="display mt-3 max-w-2xl text-3xl sm:text-5xl">
            How we invest, in four rules.
          </h2>
          <div className="mt-10 grid gap-px border border-hairline bg-hairline sm:grid-cols-2">
            {PRINCIPLES.map((p, i) => (
              <div key={p.title} className="bg-background p-8">
                <div className="text-sm text-muted tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <h3 className="mt-3 text-lg font-semibold">{p.title}</h3>
                <p className="mt-2 text-sm text-muted">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TRACK RECORD */}
      <section id="track-record" className="border-b border-hairline">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="font-mono text-sm text-accent">// Track Record</p>
          <h2 className="display mt-3 text-3xl sm:text-5xl">
            Our return, versus the index.
          </h2>
          <div className="mt-10 grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Card title="Cumulative return — us vs SPY">
                <LineChart
                  labels={labels}
                  yFormat={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`}
                  yAxisLabel="Cumulative return since inception (%)"
                  asOf={m.latest.date}
                  series={[
                    { values: usPct, color: "currentColor", label: "Whitewater" },
                    { values: spyPct, color: "#9ca3af", label: "SPY" },
                  ]}
                />
              </Card>
            </div>
            <Card title="How much is in trades">
              <div className="flex h-full items-center justify-center py-4">
                <ExposureGauge investedPct={m.exposure.investedPct} asOf={m.latest.date} />
              </div>
            </Card>
          </div>
        </div>
      </section>

      {/* NEWSLETTER */}
      <section className="border-b border-hairline">
        <div className="mx-auto max-w-5xl px-6 py-14">
          <div className="grid gap-6 sm:grid-cols-[1fr_1fr] sm:items-center">
            <div>
              <p className="font-mono text-sm text-accent">// The Letters</p>
              <h2 className="display mt-2 text-2xl sm:text-3xl">
                Our thinking, now and then.
              </h2>
              <p className="mt-2 text-sm text-muted">
                Theses and positioning notes. No spam.
              </p>
            </div>
            <NewsletterSignup source="home" />
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="mx-auto max-w-5xl px-6 py-12">
        <div className="flex flex-col justify-between gap-4 sm:flex-row">
          <span className="text-sm font-semibold uppercase tracking-[0.18em]">
            Whitewater
          </span>
          <div className="flex gap-6 text-xs uppercase tracking-[0.12em] text-muted">
            <Link href="/invest" className="hover:text-foreground">
              Invest →
            </Link>
            <Link href="/dashboard" className="hover:text-foreground">
              Members portal →
            </Link>
          </div>
        </div>
        <p className="mt-6 max-w-2xl text-xs text-muted">
          Positions and holdings are private to members. Past performance is not
          indicative of future results; nothing here is investment advice.
        </p>
      </footer>
    </div>
  );
}

const PRINCIPLES = [
  {
    title: "Concentration over diffusion",
    body: "A handful of positions we can each defend, not a basket we can't follow. If it isn't worth a real weight, it isn't worth owning.",
  },
  {
    title: "One benchmark that matters",
    body: "We measure ourselves against the S&P 500, after everything. Beating it is the only scorecard we keep.",
  },
  {
    title: "A thesis before a trade",
    body: "Every position starts as a written argument the group votes on. If the thesis breaks, the position goes — no exceptions.",
  },
  {
    title: "Fair by design",
    body: "Capital is pooled in units, like a tiny fund. Deposits and withdrawals at different times never dilute anyone's gains.",
  },
];
