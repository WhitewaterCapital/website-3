import type { EquityModel, EquityReading, EquitySignal } from "../types";
import { getFactorExport } from "@/lib/factor";
import { fetchInsiderTransactions } from "@/lib/whitewatch-data/edgar-sources";
import { getEarningsExport } from "@/lib/earnings";

// ═══════════════════════════════════════════════════════════════════════════
// Earnings Move — an EquityModel. Built 2026-09-14 in direct response to
// "it can see what earnings are upcoming and predict which way the stock
// will go on the earnings" — read plainly rather than promised in full: see
// research/equity-model-research-dossier.md's own "Earnings-surprise
// direction" row (Medium confidence — needs analyst estimate data with
// poor free coverage) and its explicit rule, "Directional single-name
// forecasting is low-signal; express as probabilistic... never a point
// price." This model does NOT predict a surprise sign or a price move.
//
// WHAT IT ACTUALLY DOES: flags which names in the fixed universe have a
// confirmed print inside WW-EARNINGS' lookahead window (earnings-engine/),
// and attaches this repo's own two already-real positioning signals to each
// one — exactly the "insider activity + factor loadings as the closest
// real proxy we actually have" the platform's own crowding research
// (PLATFORM_REBUILD_PLAN.md, "Research grounding") already settled on when
// it hit the same missing-real-signal problem for a different feature.
// Nothing here is a new statistical model; it is a new COMBINATION of three
// (now four — see TIER C below) signals that were each already real and
// already live elsewhere in this app or in this engine's own history,
// following exactly the pattern smart-money-momentum.ts set.
//
// TIER B UPDATE (same day, same session): the dossier's "poor free
// coverage" verdict on analyst estimates was re-checked against current
// (2026) provider terms rather than taken as permanently settled — see
// earnings-engine/ee/adapters/alpha_vantage_estimates.py's docstring for
// the full survey. Result: PARTIALLY real now, not still fully deferred.
// Financial Modeling Prep (confirmed, its own pricing page) and Finnhub
// (inconclusive — its docs are an unreadable JS SPA from this session's
// tooling, third-party sources disagree) do not give a clean free path.
// Alpha Vantage's EARNINGS_CALENDAR (forward consensus EPS) and EARNINGS
// (trailing actual/estimate/surprise history) functions are well-evidenced
// (not live-fetch-confirmed — see that adapter's docstring) as free, and
// earnings-engine/ee/sue.py now has a fully real, fully tested
// Standardized-Unexpected-Earnings calculator built against them. What
// this model surfaces below (`estimateNote`) is real plumbing, not a
// fabricated number: on every ticker it will currently read as "estimate
// unavailable" (ALPHA_VANTAGE_API_KEY isn't set anywhere this repo has
// been run, and even once it is, the adapter itself is still an honest
// stub — same "wired but not network-exercised" state fmp_calendar.py was
// in before this session) or, once an estimate IS wired up, "SUE
// unavailable — not yet reported": WW-EARNINGS only ever exports PRE-print
// events (report_date in the future), and SUE is mathematically undefined
// before the actual EPS behind it exists. That is a structural property of
// this calendar engine, not a missing-data gap — a future retrospective/
// eval script is the right place to ever see a non-null SUE, not this
// live "what's coming up" reading.
//
// TIER C UPDATE (same day, same session, built right after Tier B):
// revision momentum (direction/magnitude of recent estimate changes) was
// NOT deferred after all — earnings-engine/ee/revisions.py now records
// this engine's own eps_estimate for every ticker on every export run
// (live OR synthetic-demo — see that module's docstring for why this needs
// no vendor at all) into an append-only snapshot log, and computes a REAL
// day-over-day revision read from that log's own PRIOR history once a
// second real run exists. `revisionNote` below is, like `estimateNote`,
// real plumbing over an honestly-computed field, never a fabricated
// number: on this engine's FIRST-EVER run for a given ticker (the common,
// expected state early in this log's life) it reads as "revision momentum
// unavailable (insufficient snapshot history...)" — not a bug, the same
// honest-abstention shape SUE has pre-print. Once at least two real runs
// on two different `as_of` dates exist, it reads as a real, signed percent
// change ("consensus estimate raised/lowered N% vs. this engine's own
// prior recorded run").
//
// HONESTY / ABSTENTION (same contract as smart-money-momentum.ts): a
// ticker appears in `signals` ONLY when WW-EARNINGS has an event for it in
// the current export. Insider positioning is attached when available and
// stated as unavailable, by name, when not — it is never required for the
// ticker to appear, since "no signal Form 4 activity" is itself real
// information, not a gap. Factor momentum is shown as separate context,
// never blended into the directional lean, for the same reason
// FactorPanel.tsx never feeds a raw beta into a signed score. The Tier-B
// estimate/SUE read and the Tier-C revision-momentum read follow the
// identical rule: each shown as its own separate context line, never
// blended into `lean`/`score`, and each always carries its own stated
// abstain reason rather than a bare null.
//
// `lean` is deliberately built from ONE directional ingredient (insider
// net buy/sell) with an explicit rule stated in the note, not a fabricated
// probability. When WW-EARNINGS' export itself is `data_provenance:
// "synthetic-demo"` (no FMP_API_KEY configured — see earnings-engine/
// README.md) the whole reading says so plainly and should not be read as a
// real calendar.
// ═══════════════════════════════════════════════════════════════════════════

// Same fixed universe WW-Factor / Smart Money Momentum / WW-EARNINGS all
// already target — consistency across the platform's cross-sectional work,
// not invented fresh here.
export const EARNINGS_MOVE_UNIVERSE = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"] as const;

const INSIDER_PRE_PRINT_WINDOW_DAYS = 30;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

type MomentumContext = { beta: number; significant: boolean; r2: number | null } | { unavailable: string };

async function momentumContextFor(ticker: string): Promise<MomentumContext> {
  const data = await getFactorExport();
  if (!data) return { unavailable: "WW-Factor hasn't exported yet" };
  const exposure = data.exposures.find((e) => e.ticker.toUpperCase() === ticker);
  if (!exposure) return { unavailable: `not in WW-Factor's current universe (${data.exposures.length} names covered)` };
  if (exposure.confidence !== "ok" || !exposure.betas) {
    return { unavailable: `WW-Factor abstains on ${ticker}: ${exposure.abstain_reason ?? exposure.confidence}` };
  }
  const mom = exposure.betas.find((b) => b.factor === "Mom");
  if (!mom) return { unavailable: `no Mom factor loading in this window for ${ticker}` };
  return { beta: mom.beta, significant: mom.significant, r2: exposure.r2 };
}

type InsiderRead = { score: number; netWord: string; buyCount: number; sellCount: number } | { unavailable: string };

async function insiderPrePrintFor(ticker: string): Promise<InsiderRead> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let raw: any;
  try {
    raw = await fetchInsiderTransactions(ticker, { windowDays: INSIDER_PRE_PRINT_WINDOW_DAYS });
  } catch (err) {
    return { unavailable: `couldn't reach SEC EDGAR: ${(err as Error).message}` };
  }
  if (raw.status === "not_found" || raw.status === "unreachable") {
    return { unavailable: raw.message ?? `no insider-activity read for ${ticker}` };
  }
  const summary = raw.summary;
  if (!summary || summary.signalTransactionCount === 0) {
    return { unavailable: `no open-market insider buy/sell filings for ${ticker} in the trailing ${raw.windowDays ?? INSIDER_PRE_PRINT_WINDOW_DAYS} days` };
  }
  return {
    score: summary.score ?? 0,
    netWord: summary.netDirection > 0 ? "net buyers" : summary.netDirection < 0 ? "net sellers" : "mixed",
    buyCount: summary.buyCount,
    sellCount: summary.sellCount,
  };
}

// Tier-B estimate/SUE context — pure formatting over fields ee/export.py
// already computed honestly (see earnings-export.ts's module comment).
// Never recomputes SUE client-side; just reads what the export says and
// states the abstain reason verbatim when there's nothing to show.
function estimateNoteFor(event: {
  eps_estimate: number | null;
  eps_estimate_stdev: number | null;
  estimate_source: string | null;
  sue: number | null;
  sue_abstain_reason: string | null;
}): string {
  if (event.sue !== null) {
    // Not reachable by any export this engine can currently produce (see
    // the header comment) but handled for real in case a future
    // retrospective export ever populates it — never silently dropped.
    return `SUE ${event.sue >= 0 ? "+" : ""}${event.sue.toFixed(2)} (source: ${event.estimate_source ?? "unknown"})`;
  }
  if (event.eps_estimate !== null && event.eps_estimate_stdev !== null) {
    return (
      `consensus EPS estimate $${event.eps_estimate.toFixed(2)} (trailing-surprise stdev ` +
      `$${event.eps_estimate_stdev.toFixed(2)}, source: ${event.estimate_source ?? "unknown"}); ` +
      `SUE unavailable (${event.sue_abstain_reason ?? "pending print"})`
    );
  }
  if (event.eps_estimate !== null) {
    return `consensus EPS estimate $${event.eps_estimate.toFixed(2)} (no usable surprise-stdev yet); SUE unavailable (${event.sue_abstain_reason ?? "pending print"})`;
  }
  return `consensus estimate unavailable (${event.sue_abstain_reason ?? "no analyst-estimates adapter configured"})`;
}

// Tier-C revision-momentum context — same pure-formatting rule as
// estimateNoteFor: reads what earnings-engine/ee/revisions.py already
// computed honestly (see earnings-export.ts's module comment for the full
// Tier-C contract), never recomputes it client-side, and states the
// abstain reason verbatim rather than a bare "unavailable" when there
// isn't yet a second real snapshot to compare against — which is the
// expected, common state for a ticker's first-ever recorded run.
function revisionNoteFor(event: {
  revision_direction: "raised" | "lowered" | "unchanged" | null;
  revision_pct: number | null;
  revision_abstain_reason: string | null;
}): string {
  if (event.revision_direction !== null && event.revision_pct !== null) {
    if (event.revision_direction === "unchanged") {
      return `consensus estimate unchanged vs. this engine's own prior recorded run (revision momentum)`;
    }
    const sign = event.revision_pct >= 0 ? "+" : "";
    return `consensus estimate ${event.revision_direction} ${sign}${event.revision_pct.toFixed(1)}% vs. this engine's own prior recorded run (revision momentum)`;
  }
  return `revision momentum unavailable (${event.revision_abstain_reason ?? "no prior recorded run for this ticker yet"})`;
}

export const earningsMove: EquityModel = {
  meta: {
    id: "earnings-move",
    name: "Earnings Move",
    kind: "equity",
    status: "beta",
    tagline: "Who has a print coming up, and what this app's own real signals say going into it.",
    description:
      "Flags names in the fixed universe with a confirmed earnings print inside WW-EARNINGS' lookahead window, and attaches WW-Insider's real pre-print positioning, WW-Factor's real momentum context, a real consensus-EPS/SUE read (where a configured estimates adapter allows it), and a real day-over-day revision-momentum read (where this engine has recorded at least two runs for that ticker) to each. SUE is always pre-print null by construction — see earnings-engine/README.md and the equity-model research dossier's 'Earnings-surprise direction' row. Abstains honestly, never fabricates, when an input is missing.",
  },

  async read(dateISO: string): Promise<EquityReading> {
    const earningsExport = await getEarningsExport();

    if (!earningsExport) {
      return {
        date: dateISO,
        breadth: 0,
        signals: [],
        summary:
          "WW-EARNINGS hasn't exported yet (no public/data/earnings/latest.json) — run `python -m ee.export` in earnings-engine/. Nothing fabricated in its place.",
        generatedBy: "Earnings Move",
      };
    }

    const universeEvents = earningsExport.events.filter((e) =>
      (EARNINGS_MOVE_UNIVERSE as readonly string[]).includes(e.ticker.toUpperCase()),
    );

    const signals: EquitySignal[] = [];

    for (const event of universeEvents) {
      const [mom, insider] = await Promise.all([
        momentumContextFor(event.ticker),
        insiderPrePrintFor(event.ticker),
      ]);

      const momNote =
        "unavailable" in mom
          ? `factor context unavailable (${mom.unavailable})`
          : `Mom beta ${mom.beta >= 0 ? "+" : ""}${mom.beta.toFixed(2)}${mom.significant ? "" : " (not significant)"} (WW-Factor)`;

      let lean = "no lean — no directional real input available";
      let score = 0;
      if (!("unavailable" in insider)) {
        score = clamp(insider.score, -100, 100);
        lean =
          insider.netWord === "mixed"
            ? "no lean — insiders mixed"
            : `${insider.netWord === "net buyers" ? "bullish" : "bearish"}-lean — the one directional real input (insider ${insider.netWord}, ${insider.buyCount} buy/${insider.sellCount} sell over ${INSIDER_PRE_PRINT_WINDOW_DAYS}d pre-print) points that way; factor momentum shown as separate context, not blended in`;
      }
      const insiderNote = "unavailable" in insider ? `insider positioning unavailable (${insider.unavailable})` : `insiders ${insider.netWord} pre-print`;
      const estimateNote = estimateNoteFor(event);
      const revisionNote = revisionNoteFor(event);

      signals.push({
        symbol: event.ticker,
        score,
        note:
          `Print ${event.report_date}${event.session ? ` (${event.session})` : ""}. ${lean}. ` +
          `${insiderNote}; ${momNote}; ${estimateNote}; ${revisionNote}. Calendar source: ${earningsExport.data_provenance}` +
          (earningsExport.data_provenance === "synthetic-demo" ? " — NOT a real date, demo only." : "."),
      });
    }

    signals.sort((a, b) => b.score - a.score);
    const breadth = signals.length > 0 ? Math.round(signals.reduce((s, x) => s + x.score, 0) / signals.length) : 0;

    const demoFlag = earningsExport.data_provenance === "synthetic-demo" ? " CALENDAR IS SYNTHETIC-DEMO — no FMP_API_KEY configured; dates below are not real." : "";
    const summary =
      `${signals.length} of ${EARNINGS_MOVE_UNIVERSE.length} tracked names have a print in the next ${earningsExport.lookahead_days} days ` +
      `(as of ${earningsExport.as_of}).${demoFlag} Each carries WW-Insider's real pre-print positioning, WW-Factor's real momentum ` +
      `context, a consensus-EPS/SUE read where available, and a day-over-day revision-momentum read where this engine has recorded ` +
      `enough runs — calendar data only otherwise; not a surprise-direction or price-move prediction (see earnings-engine/README.md).`;

    return { date: dateISO, breadth, signals, summary, generatedBy: "Earnings Move" };
  },
};
