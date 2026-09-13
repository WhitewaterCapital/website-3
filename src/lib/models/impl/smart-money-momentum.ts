import type { EquityModel, EquityReading, EquitySignal } from "../types";
import { getFactorExport } from "@/lib/factor";
import { fetchInsiderTransactions } from "@/lib/whitewatch-data/edgar-sources";

// ═══════════════════════════════════════════════════════════════════════════
// Smart Money Momentum — an EquityModel (PLATFORM_REBUILD_PLAN.md priority
// #11). A cross-sectional screen combining two signals this app already
// computes for real, over the same fixed universe WW-Factor already covers:
//
//   - WW-Insider's net insider buy/sell direction, over a trailing 90-day
//     window (SEC EDGAR Form 4 — the same source already powering Distresse's
//     Positioning/crowding dimension).
//   - WW-Factor's momentum ("Mom") factor beta from its Fama-French + Mom
//     regression (the same source already powering Distresse's Factor
//     exposure dimension).
//
// RESEARCH GROUNDING (see PLATFORM_REBUILD_PLAN.md "Quant model research"):
// academic work on insider Form 3/4 signals (Alpha Architect's review) and on
// combining insider ownership with momentum specifically (TEJ) supports using
// the two together rather than either alone — they capture different,
// complementary information. This screen is exactly that combination, and
// nothing more: no fabricated third ingredient, no options/IV data (this app
// has no free source for that — see the Options/Alpha Vantage roadblock).
//
// WHY THIS IS DIFFERENT FROM FactorPanel's "descriptive risk context only"
// rule (see that file's own top-of-file comment): a single name's momentum
// BETA, alone, really is purely descriptive — a negative Mom beta just means
// "style tilt away from recent winners," not a sell signal, so FactorPanel's
// numbers are deliberately never fed into conviction.ts's composite score.
// This model does something categorically different: it's a CROSS-SECTIONAL
// RELATIVE RANK across a small, fixed universe (not a single name's absolute
// score), and it combines the beta with a genuinely directional real input
// (insiders buying or selling with their own money) — which is the standard
// academic construction of a momentum-style factor screen, not a
// reinterpretation of what one beta means in isolation. Same rule still
// applies, though: this model's scores are NOT fed into conviction.ts either
// — it's a standalone screen, not an ingredient in any single-name verdict.
//
// HONESTY / ABSTENTION: a ticker appears in `signals` ONLY when BOTH real
// inputs are available for it (WW-Factor confidence === "ok" for that name,
// AND at least one signal Form 4 transaction in the trailing window). A name
// missing either input is left OUT of `signals` entirely — never given a
// fabricated neutral score — and the gap is named plainly in `summary`.
// AS OF 2026-09-13, WW-Factor's live export only covers 3 synthetic-demo
// tickers (DEMO-A/B/C; see PLATFORM_REBUILD_PLAN.md's Roadblocks) — until
// factor-engine is re-run against real Tiingo data for this universe, EVERY
// name below will correctly show empty, not because this screen is broken,
// but because its one real momentum-beta input doesn't cover any real ticker
// yet. That is intentional honest-but-empty scaffolding, the same pattern
// this whole codebase already uses elsewhere, not a bug to hide.
// ═══════════════════════════════════════════════════════════════════════════

// The same 6-name universe WW-Factor's own fixed universe already targets
// (and the same set Intra/Exitus and Incepta already cover) — chosen for
// consistency across this session's cross-sectional work, not invented fresh.
export const SMART_MONEY_UNIVERSE = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"] as const;

const INSIDER_WINDOW_DAYS = 90;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

type MomentumRead = { beta: number; significant: boolean; r2: number | null; tilt: number };

async function momentumForTicker(ticker: string): Promise<MomentumRead | { unavailable: string }> {
  const data = await getFactorExport();
  if (!data) return { unavailable: "WW-Factor hasn't exported yet" };

  const exposure = data.exposures.find((e) => e.ticker.toUpperCase() === ticker);
  if (!exposure) return { unavailable: `not in WW-Factor's current universe (${data.exposures.length} names covered)` };
  if (exposure.confidence !== "ok" || !exposure.betas) {
    return { unavailable: `WW-Factor abstains on ${ticker}: ${exposure.abstain_reason ?? exposure.confidence}` };
  }

  const mom = exposure.betas.find((b) => b.factor === "Mom");
  if (!mom) return { unavailable: `no Mom factor loading in this window for ${ticker}` };

  // Same linear-scaling convention as this session's other real-data screens
  // (fred.ts's T10Y2Y read, distresse.ts's regime dimension): deliberately
  // simple, explicitly unbacktested, stated as such in the note.
  const tilt = clamp(mom.beta * 40, -100, 100);
  return { beta: mom.beta, significant: mom.significant, r2: exposure.r2, tilt };
}

type InsiderRead = { score: number; netWord: string; buyCount: number; sellCount: number; distinctInsiders: number };

async function insiderForTicker(ticker: string): Promise<InsiderRead | { unavailable: string }> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let raw: any;
  try {
    raw = await fetchInsiderTransactions(ticker, { windowDays: INSIDER_WINDOW_DAYS });
  } catch (err) {
    return { unavailable: `couldn't reach SEC EDGAR: ${(err as Error).message}` };
  }
  if (raw.status === "not_found" || raw.status === "unreachable") {
    return { unavailable: raw.message ?? `no insider-activity read for ${ticker}` };
  }
  const summary = raw.summary;
  if (!summary || summary.signalTransactionCount === 0) {
    return { unavailable: `no open-market insider buy/sell filings for ${ticker} in the trailing ${raw.windowDays ?? INSIDER_WINDOW_DAYS} days` };
  }
  return {
    score: summary.score ?? 0,
    netWord: summary.netDirection > 0 ? "net buyers" : summary.netDirection < 0 ? "net sellers" : "mixed",
    buyCount: summary.buyCount,
    sellCount: summary.sellCount,
    distinctInsiders: summary.distinctInsiders,
  };
}

export const smartMoneyMomentum: EquityModel = {
  meta: {
    id: "smart-money-momentum",
    name: "Smart Money Momentum",
    kind: "equity",
    status: "live",
    tagline: "Insider net-buying × momentum-factor beta, cross-sectional, over a fixed 6-name universe.",
    description:
      "A research-style cross-sectional screen, not a single-name verdict: ranks WW-Factor's fixed universe by combining two real signals — WW-Insider's real SEC EDGAR net insider buy/sell direction and WW-Factor's real momentum ('Mom') factor beta — per academic research on combining the two (see PLATFORM_REBUILD_PLAN.md). A name appears only when BOTH real inputs are available for it; abstains honestly, never fabricates, for the rest. Not fed into Distresse's or any single-name composite conviction score — same 'descriptive/screen, not a verdict' boundary FactorPanel already draws around raw factor betas.",
  },

  async read(dateISO: string): Promise<EquityReading> {
    const rows = await Promise.all(
      SMART_MONEY_UNIVERSE.map(async (ticker) => {
        const [mom, insider] = await Promise.all([momentumForTicker(ticker), insiderForTicker(ticker)]);
        return { ticker, mom, insider };
      }),
    );

    const signals: EquitySignal[] = [];
    const skipped: string[] = [];

    for (const { ticker, mom, insider } of rows) {
      if ("unavailable" in mom) {
        skipped.push(`${ticker}: momentum unavailable (${mom.unavailable})`);
        continue;
      }
      if ("unavailable" in insider) {
        skipped.push(`${ticker}: insider unavailable (${insider.unavailable})`);
        continue;
      }
      // A simple, stated average of two already -100..100-scaled real reads
      // — not a fitted or backtested weighting scheme.
      const combined = clamp(Math.round((mom.tilt + insider.score) / 2), -100, 100);
      signals.push({
        symbol: ticker,
        score: combined,
        note:
          `Mom beta ${mom.beta >= 0 ? "+" : ""}${mom.beta.toFixed(2)}${mom.significant ? "" : " (not significant this window)"} ` +
          `(WW-Factor, R² ${mom.r2 != null ? (mom.r2 * 100).toFixed(0) + "%" : "n/a"}); insiders ${insider.netWord} over ${INSIDER_WINDOW_DAYS}d ` +
          `(${insider.buyCount} buy/${insider.sellCount} sell across ${insider.distinctInsiders} insider(s), SEC EDGAR). ` +
          `Combined tilt is a stated simple average of the two, not a backtested weighting — a cross-sectional rank input, not a standalone buy/sell call.`,
      });
    }

    signals.sort((a, b) => b.score - a.score);

    const breadth = signals.length > 0 ? Math.round(signals.reduce((s, x) => s + x.score, 0) / signals.length) : 0;

    const coverageLine =
      signals.length > 0
        ? `${signals.length} of ${SMART_MONEY_UNIVERSE.length} names had both real inputs available and are ranked below.`
        : `0 of ${SMART_MONEY_UNIVERSE.length} names had both real inputs available this read — nothing fabricated in their place.`;
    const skipLine = skipped.length > 0 ? ` Not ranked: ${skipped.join("; ")}.` : "";

    const summary =
      `Cross-sectional screen combining WW-Insider's real SEC EDGAR net buy/sell direction with WW-Factor's ` +
      `real momentum ('Mom') beta, over the fixed ${SMART_MONEY_UNIVERSE.length}-name universe ` +
      `(${SMART_MONEY_UNIVERSE.join(", ")}). ${coverageLine}${skipLine} Descriptive/research screen — not fed into ` +
      `any single-name composite conviction score.`;

    return {
      date: dateISO,
      breadth,
      signals,
      summary,
      generatedBy: "Smart Money Momentum",
    };
  },
};
