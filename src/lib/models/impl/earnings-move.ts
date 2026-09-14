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
// signals that were each already real and already live elsewhere in this
// app, following exactly the pattern smart-money-momentum.ts set.
//
// HONESTY / ABSTENTION (same contract as smart-money-momentum.ts): a
// ticker appears in `signals` ONLY when WW-EARNINGS has an event for it in
// the current export. Insider positioning is attached when available and
// stated as unavailable, by name, when not — it is never required for the
// ticker to appear, since "no signal Form 4 activity" is itself real
// information, not a gap. Factor momentum is shown as separate context,
// never blended into the directional lean, for the same reason
// FactorPanel.tsx never feeds a raw beta into a signed score.
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

export const earningsMove: EquityModel = {
  meta: {
    id: "earnings-move",
    name: "Earnings Move",
    kind: "equity",
    status: "beta",
    tagline: "Who has a print coming up, and what this app's own real signals say going into it.",
    description:
      "Flags names in the fixed universe with a confirmed earnings print inside WW-EARNINGS' lookahead window, and attaches WW-Insider's real pre-print positioning and WW-Factor's real momentum context to each. Deliberately NOT a surprise-direction or price-move predictor — see earnings-engine/README.md and the equity-model research dossier's own 'Medium confidence, needs paid estimate data' verdict on that harder problem. Abstains honestly, never fabricates, when an input is missing.",
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

      signals.push({
        symbol: event.ticker,
        score,
        note:
          `Print ${event.report_date}${event.session ? ` (${event.session})` : ""}. ${lean}. ` +
          `${insiderNote}; ${momNote}. Calendar source: ${earningsExport.data_provenance}` +
          (earningsExport.data_provenance === "synthetic-demo" ? " — NOT a real date, demo only." : "."),
      });
    }

    signals.sort((a, b) => b.score - a.score);
    const breadth = signals.length > 0 ? Math.round(signals.reduce((s, x) => s + x.score, 0) / signals.length) : 0;

    const demoFlag = earningsExport.data_provenance === "synthetic-demo" ? " CALENDAR IS SYNTHETIC-DEMO — no FMP_API_KEY configured; dates below are not real." : "";
    const summary =
      `${signals.length} of ${EARNINGS_MOVE_UNIVERSE.length} tracked names have a print in the next ${earningsExport.lookahead_days} days ` +
      `(as of ${earningsExport.as_of}).${demoFlag} Each carries WW-Insider's real pre-print positioning and WW-Factor's real momentum ` +
      `context where available — calendar data only otherwise; not a surprise-direction or price-move prediction (see earnings-engine/README.md).`;

    return { date: dateISO, breadth, signals, summary, generatedBy: "Earnings Move" };
  },
};
