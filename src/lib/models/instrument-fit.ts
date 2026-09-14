import type {
  TradeIdea,
  Instrument,
  IdeaTimeframe,
  IdeaCatalystType,
} from "./types";
import type { OptionsSummary, OptionsStatus } from "./options-export";

// ═══════════════════════════════════════════════════════════════════════════
// Instrument Fit — a small, honest, non-fabricating advisory read on whether
// the INSTRUMENT a member picked (long / short / call / put / future) is
// well-suited to the THESIS they described, independent of whether the
// thesis itself is any good.
//
// WHY THIS EXISTS, AND WHY IT'S SEPARATE FROM DISTRESSE: distresse.ts scores
// the thesis — six real, weighted dimensions (macro, factor, positioning,
// valuation, sentiment, liquidity) asking "is this a good bet on this
// ticker, in this direction, right now?" Nothing in that file, or anywhere
// else in this codebase, asks the genuinely different question this module
// answers: "given that thesis, is THIS INSTRUMENT — this specific
// long/short/call/put/future — well-matched to it, or does the wrapper
// introduce its own risk on top of the thesis being right?" A six-month
// fundamental long expressed as a 30-day call is a real, well-documented
// example of a good thesis turned into a bad trade by the choice of
// instrument — see the theta citation below. Distresse has no way to see
// that gap because it never looks at expiration or option pricing at all
// (distresse.ts's own header: "No Options (Alpha Vantage) data ... per its
// own header comment is deliberately never folded into a directional
// composite; same reasoning applies here" — OptionsPanel's magnitude-only
// IV/expected-move read has no directional sign to give a signed composite,
// and this module's flags aren't directional either, for the same reason).
// This module is NOT wired into distresse.ts's scoring and does not touch
// that file. It is a second, independent, additive read — never a single
// opaque "instrument score," and never a directive "you should do X." Every
// output is framed as "here's what to weigh," matching this app's
// established research-read-not-investment-advice convention (see
// src/app/smart-money/page.tsx, src/app/earnings/page.tsx).
//
// ── REAL DATA THIS MODULE ACTUALLY HAS, AND WHAT IT HONESTLY DOESN'T ───────
// The only real per-ticker market data this platform can supply about an
// options market is the Alpha Vantage HISTORICAL_OPTIONS read wired through
// src/lib/whitewatch-data/{alphavantage-options,options-summary}.js and
// typed as OptionsSummary (src/lib/models/options-export.ts). Every one of
// OptionsSummary's seven `status` values is handled BELOW, distinctly, by
// optionsDataStateConsideration() — never collapsed into a generic "no
// data," per this module's own honest-abstention discipline:
//   not_configured — no ALPHA_VANTAGE_API_KEY set; no attempt was made at all
//   not_applicable — a real "success" response with zero contracts (no
//                    listed options for this ticker — the common case)
//   no_data        — options exist but no usable chain/spot came back
//   plan_gated     — Alpha Vantage says this endpoint isn't on this key's
//                    plan; retrying will not change that
//   rate_limited   — the free tier's request budget is exhausted for now;
//                    may clear soon
//   error          — a genuine fetch/timeout/malformed-response failure
//   ok             — a real, usable chain with a resolvable spot and ATM IV
// Only "ok" carries real option pricing (atmIv / expectedMovePct / spot /
// expiration). Every other status means this module's considerations are
// STRUCTURAL and TIMEFRAME-BASED ONLY — informed by how options generally
// behave (real, cited, vendor-independent facts about theta and leverage),
// never by this specific ticker's actual, current option prices. That
// distinction is stated explicitly in `ivInformed` on the result AND in the
// plain-language text of every consideration touching it — per this task's
// explicit requirement never to imply a pricing-informed read when the
// read isn't actually informed by pricing.
//
// Even when status is "ok", this module does NOT claim to know whether the
// current implied volatility is "cheap" or "expensive" for this ticker.
// The standard framing for that judgment is IV's PERCENTILE/RANK against
// its own trailing range — see Charles Schwab, "Using Implied Volatility
// Percentages and Rankings" (schwab.com/learn/story/using-implied-
// volatility-percentiles, fetched 2026-09-14): "When IV percentile is
// high, options premiums are relatively high... When IV percentile is low,
// options premiums are relatively low" — a comparison against the ticker's
// OWN historical IV range, not its level in isolation. Alpha Vantage's
// HISTORICAL_OPTIONS endpoint (see alphavantage-options.js's header)
// returns a single trading day's chain, not a volatility time series, so
// this platform has no IV history to rank against. This module reports the
// real, current, absolute ATM IV level and expected move honestly, but
// never a "cheap vs. expensive right now" verdict it has no data to
// support.
//
// ── THE STRUCTURAL RESEARCH THIS MODULE IS GROUNDED IN (fetched 2026-09-14,
// via WebSearch/WebFetch — this sandbox has no outbound internet access
// either, same constraint documented in alphavantage-options.js's header) ──
//   1. Options Industry Council (OIC — the options exchanges' and OCC's own
//      investor-education site), "Leverage & Risk":
//      https://www.optionseducation.org/optionsoverview/leverage-risk —
//      quoted: buying an option, "your potential loss is limited to the
//      amount you paid for the option contract" (a defined max loss a short
//      stock position never has — short-stock loss is theoretically
//      unlimited), but the same leverage that caps the dollar loss also
//      means "leverage could magnify the investment's percentage loss" if
//      the underlying doesn't move favorably before expiration.
//   2. OIC, "Theta": https://www.optionseducation.org/advancedconcepts/theta
//      — quoted: an option's time value "will decrease (or decay) with the
//      passage of time," and this decay is non-linear — "options with the
//      least remaining time until expiration will tend to decay the most."
//      This is the concrete mechanism behind the exact scenario this task
//      was built to catch: a genuinely good, slow-developing thesis
//      expressed via a short-dated contract pays theta the whole way and
//      can expire worthless even if the direction eventually proves right —
//      the contract's clock runs independent of whether the thesis is
//      correct.
//   3. OIC, "The Crush Is Real":
//      https://www.optionseducation.org/news/the-crush-is-real — a worked
//      example: a trader buys a $105 call at $2.90 with the stock at $100;
//      after earnings the stock rises to $106 (the predicted direction) but
//      the call falls to $2.10 anyway, because implied volatility fell from
//      80% pre-announcement to 30% post-announcement — "the right direction
//      may not overcome the changes in premium." This is "volatility
//      crush": IV is bid up into a dated catalyst and typically collapses
//      once the event resolves, which is a real, separate risk from
//      theta/timeframe fit and specific to earnings/dated-catalyst bets.
//   4. Charles Schwab, "Using Implied Volatility Percentages and Rankings"
//      — cited above re: IV percentile/rank as the standard cheap-vs-
//      expensive framing this platform's single-day chain can't support.
// ═══════════════════════════════════════════════════════════════════════════

export type InstrumentFitTone = "flag" | "context";
// flag    — concretely worth weighing before sizing THIS instrument choice
//           for THIS thesis; the kind of thing that changes how you'd size
//           or structure the trade, not just background color.
// context — grounding/informational: real, relevant, but not by itself an
//           objection to the instrument chosen.

export interface InstrumentFitConsideration {
  label: string; // short heading, e.g. "Time decay vs. thesis horizon"
  detail: string; // plain-language sentence(s) — "here's what to weigh," never a directive
  tone: InstrumentFitTone;
}

export interface InstrumentFitResult {
  ticker: string;
  instrument: Instrument;
  timeframe: IdeaTimeframe; // resolved (idea.timeframe ?? "position")
  catalystType: IdeaCatalystType; // resolved (idea.catalystType ?? "general-thesis")
  isOptionsInstrument: boolean; // true for "call" | "put"
  optionsStatus: OptionsStatus;
  // True only when at least one consideration below is grounded in this
  // ticker's REAL, current option pricing (status "ok"). False means every
  // consideration is structural/timeframe-based — never implied to be more
  // than that. See the header note on why "ok" itself still isn't an
  // IV-percentile / cheap-vs-expensive read.
  ivInformed: boolean;
  considerations: InstrumentFitConsideration[];
  // One plain-language paragraph synthesizing the considerations. Never a
  // verdict, never "you should" — states what's worth weighing and why,
  // same voice as StressVerdict.bottomLine but explicitly NOT a go/no-go.
  summary: string;
  generatedBy: string;
}

const dashTicker = "this ticker";

function pctFmt(x: number | null | undefined): string {
  return x == null ? "an unresolved %" : `${(x * 100).toFixed(1)}%`;
}

function priceFmt(x: number | null | undefined): string {
  return x == null ? "an unresolved price" : `$${x.toFixed(2)}`;
}

const TIMEFRAME_WINDOW: Record<IdeaTimeframe, string> = {
  intraday: "hours — closed today or next session",
  swing: "days to a few weeks",
  position: "weeks to a few months",
  "long-term": "6+ months",
};

// ── Consideration 1: what the options data actually says (always first) ──
// Handles every OptionsStatus distinctly, per this task's explicit
// requirement — never collapsed into a generic "no data." This is also
// where `ivInformed` gets its answer: only "ok" carries real pricing.
function optionsDataStateConsideration(o: OptionsSummary): InstrumentFitConsideration {
  const label = "Options market data for this ticker";
  const t = o.ticker || dashTicker;
  switch (o.status) {
    case "not_configured":
      return {
        label,
        tone: "flag",
        detail:
          `Options data isn't configured on this platform yet (no ALPHA_VANTAGE_API_KEY set) — every consideration ` +
          `below is structural/timeframe-based only, not informed by ${t}'s actual option pricing, expiration menu, ` +
          `or even confirmation that ${t} has listed options at all.`,
      };
    case "not_applicable":
      return {
        label,
        tone: "flag",
        detail:
          `Alpha Vantage returned no listed options chain for ${t}. Most tickers on this platform genuinely have no ` +
          `exchange-listed options, so this is the expected result far more often than not — but it also means a ` +
          `call/put on ${t} may not be executable as described at all. Confirm directly with IBKR before assuming a ` +
          `listed contract exists.`,
      };
    case "no_data":
      return {
        label,
        tone: "context",
        detail:
          `${t} has listed option expirations, but no usable chain/spot came back on this pull` +
          `${o.reason ? ` (${o.reason})` : ""} — usually a temporary data gap, not evidence options don't exist for ` +
          `this name. Every consideration below is structural/timeframe-based only for now, not informed by real ` +
          `pricing.`,
      };
    case "plan_gated":
      return {
        label,
        tone: "flag",
        detail:
          `Alpha Vantage says the options endpoint isn't available on this API key's current plan` +
          `${o.reason ? ` ("${o.reason}")` : ""} — this will not resolve on its own. Every consideration below is ` +
          `structural/timeframe-based only, not informed by ${t}'s real option pricing.`,
      };
    case "rate_limited":
      return {
        label,
        tone: "context",
        detail:
          `Alpha Vantage's free-tier request budget was hit on this pull` +
          `${o.reason ? ` (${o.reason})` : ""} — temporary, may clear within the hour or by tomorrow's daily reset. ` +
          `Every consideration below is structural/timeframe-based only for now, not informed by ${t}'s real option ` +
          `pricing.`,
      };
    case "error":
      return {
        label,
        tone: "flag",
        detail:
          `Couldn't reach Alpha Vantage for ${t}'s options data on this pull` +
          `${o.reason ? ` (${o.reason})` : ""}. Every consideration below is structural/timeframe-based only, not ` +
          `informed by real option pricing.`,
      };
    case "ok": {
      const exp = o.expiration ?? "an unresolved date";
      const basis = o.expirationBasis === "standard-monthly" ? "next standard-monthly" : "nearest listed";
      const asOfTxt = o.quoteDate ?? "the most recent trading day Alpha Vantage returned";
      return {
        label,
        tone: "context",
        detail:
          `${t} has a confirmed, real options chain as of ${asOfTxt} — ${o.contractsCount ?? "some"} contracts at ` +
          `the ${basis} expiration (${exp}, ${o.daysToExpiration ?? "an unresolved number of"} days out). The ` +
          `IV-based considerations below are grounded in this real chain, not a generic assumption about how ` +
          `options behave.`,
      };
    }
    default:
      // Exhaustive by OptionsStatus's own union; kept as a defensive
      // fallback rather than a crash if this platform's status set ever
      // grows without this file being updated to match.
      return {
        label,
        tone: "flag",
        detail: `Unrecognized options data status ("${String((o as { status?: unknown }).status)}") — treated as no usable read.`,
      };
  }
}

// ── Consideration set for instrument = "call" | "put" ──────────────────────

function leverageMaxLossConsideration(instrument: Instrument): InstrumentFitConsideration {
  const side = instrument === "put" ? "a put" : "a call";
  return {
    label: "Leverage vs. defined max loss",
    tone: "context",
    detail:
      `Buying ${side} caps the max loss at the premium paid — Options Industry Council (OIC): "your potential loss ` +
      `is limited to the amount you paid for the option contract," unlike a naked short stock position, which has ` +
      `theoretically unlimited loss. The same leverage that caps the dollar loss also means a smaller move than ` +
      `expected, or one that arrives too slowly, hits the position's percentage return much harder than the same ` +
      `move would hit stock held directly — OIC's own framing: "leverage could magnify the investment's percentage ` +
      `loss" (optionseducation.org/optionsoverview/leverage-risk).`,
  };
}

// The core "is the timeframe/expiration fit right" read. Real (status "ok")
// vs. structural (every other status) is handled explicitly rather than
// silently — see the header note on never implying a pricing-informed read
// when it isn't one.
function timeframeVsThetaConsideration(
  timeframe: IdeaTimeframe,
  o: OptionsSummary,
): InstrumentFitConsideration {
  const window = TIMEFRAME_WINDOW[timeframe];
  const thetaCitation =
    'an option\'s time value "will decrease (or decay) with the passage of time," and non-linearly — ' +
    '"options with the least remaining time until expiration will tend to decay the most" ' +
    "(OIC, optionseducation.org/advancedconcepts/theta)";

  if (o.status === "ok" && o.daysToExpiration != null) {
    const dte = o.daysToExpiration;
    if (timeframe === "long-term" && dte < 180) {
      return {
        label: "Time decay vs. thesis horizon",
        tone: "flag",
        detail:
          `This is a long-term thesis (${window}), but the real contract this platform read for ${o.ticker} expires ` +
          `in ${dte} days — well short of that window. Because ${thetaCitation}, a contract this short can run out ` +
          `of time (and lose to theta) before a multi-quarter thesis actually plays out, even if the direction ` +
          `eventually proves right. Worth weighing a further-dated expiration (a LEAPS-style contract, if one's ` +
          `listed) against holding the stock directly, which has no expiration to race.`,
      };
    }
    if (timeframe === "position" && dte < 30) {
      return {
        label: "Time decay vs. thesis horizon",
        tone: "flag",
        detail:
          `This is a position-timeframe thesis (${window}), but the real contract this platform read for ${o.ticker} ` +
          `expires in ${dte} days — shorter than the window this thesis is meant to play out over. Because ` +
          `${thetaCitation}, that gap is a real, separate risk on top of whatever Distresse's read on the thesis ` +
          `itself says: theta can erode the position before the thesis has had its full window to work, `+
          `independent of direction.`,
      };
    }
    return {
      label: "Time decay vs. thesis horizon",
      tone: "context",
      detail:
        `The real contract this platform read for ${o.ticker} (${dte} days to expiration) is reasonably in line ` +
        `with a ${timeframe} thesis's own window (${window}). Theta still applies — ${thetaCitation} — but the ` +
        `contract isn't obviously shorter than the thesis needs, unlike a case where a multi-month thesis meets a ` +
        `days-out expiration.`,
    };
  }

  // No real chain to check the actual expiration against — purely
  // structural: state the mechanism, honestly note this platform can't
  // currently confirm whether it applies to the specific contract a member
  // would actually pick.
  const flagWorthy = timeframe === "position" || timeframe === "long-term";
  return {
    label: "Time decay vs. thesis horizon",
    tone: flagWorthy ? "flag" : "context",
    detail:
      `This is a ${timeframe} thesis (${window}). Time decay (theta) is a well-documented, real headwind for ` +
      `options bought and held through a slow-developing thesis: ${thetaCitation} — a short-dated contract can ` +
      `expire before the thesis plays out even if the direction eventually proves right, independent of whether ` +
      `Distresse's read on the thesis itself is strong. This platform doesn't have a real options chain for ` +
      `${o.ticker} on this pull (see the options-data status above), so there's no way here to say whether the ` +
      `specific expiration a member would actually pick is short relative to this thesis — check the real ` +
      `expiration menu with IBKR directly before sizing.`,
  };
}

function earningsCrushConsideration(): InstrumentFitConsideration {
  return {
    label: "Earnings-specific: implied volatility crush",
    tone: "flag",
    detail:
      `This idea is framed around a single dated event (an earnings print). Options priced into a known catalyst ` +
      `like this are a documented, separate risk from the timeframe/theta fit above: implied volatility is typically ` +
      `bid up going into the print and then falls sharply once the event resolves and uncertainty clears — OIC's ` +
      `own worked example ("The Crush Is Real"): a $105 call bought at $2.90 with the stock at $100 fell to $2.10 ` +
      `even after the stock rose to $106 (the predicted direction), because implied volatility fell from 80% to 30% ` +
      `around the print — "the right direction may not overcome the changes in premium." Being right on direction ` +
      `is not, by itself, enough to make a pre-earnings option purchase profitable.`,
  };
}

function ivPricingConsideration(o: OptionsSummary): InstrumentFitConsideration | null {
  if (o.status !== "ok" || o.atmIv == null || o.expectedMovePct == null) return null;
  return {
    label: "What this ticker's real option pricing currently says",
    tone: "context",
    detail:
      `${o.ticker}'s at-the-money implied volatility for the ${o.expiration ?? "read"} expiration is ` +
      `${pctFmt(o.atmIv)} annualized, pricing roughly a ±${pctFmt(o.expectedMovePct)} (${priceFmt(o.expectedMoveDollars)}) ` +
      `one-standard-deviation move by expiration — real and current, but NOT a "cheap vs. expensive" read: that ` +
      `judgment is normally made against this IV's own percentile/rank over its trailing range (Charles Schwab: ` +
      `"When IV percentile is high, options premiums are relatively high... When IV percentile is low, options ` +
      `premiums are relatively low"), and this platform only has a single day's chain, not an IV history, to rank ` +
      `against. Weigh whether the thesis expects a move bigger than this implied band, not just whether it's ` +
      `right in direction.`,
  };
}

// ── Consideration set for instrument = "long" | "short" ────────────────────

function noExpirationConsideration(timeframe: IdeaTimeframe): InstrumentFitConsideration {
  const window = TIMEFRAME_WINDOW[timeframe];
  return {
    label: "No expiration clock",
    tone: "context",
    detail:
      `Stock has no expiration and pays no theta — direct exposure can sit through a ${timeframe} thesis's own ` +
      `window (${window}) on its own timeline, without racing a contract's clock the way an option bought to ` +
      `express the same thesis would (OIC: an option's time value "will decrease... with the passage of time"). ` +
      `That's a real structural advantage of stock for a slow-developing thesis specifically.`,
  };
}

function unlimitedShortLossConsideration(): InstrumentFitConsideration {
  return {
    label: "Unlimited loss vs. a defined-risk alternative",
    tone: "flag",
    detail:
      `A short stock position has theoretically unlimited loss if the name rallies against it. A long put ` +
      `expressing the same bearish thesis caps the max loss at the premium paid instead — OIC: "your potential ` +
      `loss is limited to the amount you paid for the option contract." Worth weighing if defined risk matters more ` +
      `for this idea's sizing than the capital efficiency and lack of expiration a straight short position offers.`,
  };
}

function optionsAlternativeConsideration(
  instrument: Instrument,
  timeframe: IdeaTimeframe,
  o: OptionsSummary,
): InstrumentFitConsideration {
  const side = instrument === "short" ? "put" : "call";
  if (o.status === "ok") {
    const window = TIMEFRAME_WINDOW[timeframe];
    return {
      label: `Alternative: expressing this as a ${side} instead of stock`,
      tone: "context",
      detail:
        `${o.ticker} does have a confirmed, real options chain as of ${o.quoteDate ?? "the most recent trading day"} ` +
        `(expiration ${o.expiration ?? "unresolved"}, ${o.daysToExpiration ?? "an unresolved number of"} days out; ` +
        `implied ±${pctFmt(o.expectedMovePct)} move). A ${side} on ${o.ticker} would cap max loss at the premium ` +
        `paid and require less capital than the equivalent stock position, at the real cost of theta decay and ` +
        `needing the move to happen inside that expiration window — which matters more the further this thesis's ` +
        `own window (${window}) runs past the contract's ${o.daysToExpiration ?? "unresolved"}-day expiration. Worth ` +
        `weighing against the stock position chosen, especially if defined risk matters more here than unlimited ` +
        `upside/downside exposure.`,
    };
  }
  return {
    label: `Alternative: expressing this as a ${side} instead of stock`,
    tone: "context",
    detail:
      `Whether a defined-risk options alternative even exists for ${o.ticker} can't currently be confirmed from ` +
      `this platform's real options data on this pull (status: ${o.status}${o.reason ? ` — ${o.reason}` : ""}) — see ` +
      `the options-data consideration above. This is not a claim that one does or doesn't exist, only that this ` +
      `read can't ground it in real pricing right now.`,
  };
}

// ── Consideration for instrument = "future" ─────────────────────────────────

function futuresScopeConsideration(): InstrumentFitConsideration {
  return {
    label: "Scope limitation: futures aren't covered by this platform's options read",
    tone: "context",
    detail:
      `This platform's only real options-market data source (Alpha Vantage HISTORICAL_OPTIONS) covers listed ` +
      `equity/ETF options, not futures or futures options — so this module has no real data to compare a futures ` +
      `position against. Futures already carry their own built-in expiration and daily margin/mark-to-market ` +
      `dynamics, which are a genuinely different mechanism from equity-option theta and are out of scope for the ` +
      `real data this read is grounded in; this is stated honestly rather than reasoning about futures by analogy ` +
      `to equity options.`,
  };
}

// ── Orchestration ────────────────────────────────────────────────────────

export function assessInstrumentFit(idea: TradeIdea, options: OptionsSummary): InstrumentFitResult {
  const ticker = idea.ticker.trim().toUpperCase();
  const instrument = idea.instrument;
  const timeframe: IdeaTimeframe = idea.timeframe ?? "position";
  const catalystType: IdeaCatalystType = idea.catalystType ?? "general-thesis";
  const isOptionsInstrument = instrument === "call" || instrument === "put";
  const ivInformed = options.status === "ok" && options.atmIv != null;

  const considerations: InstrumentFitConsideration[] = [optionsDataStateConsideration(options)];

  if (isOptionsInstrument) {
    considerations.push(leverageMaxLossConsideration(instrument));
    considerations.push(timeframeVsThetaConsideration(timeframe, options));
    if (catalystType === "earnings") considerations.push(earningsCrushConsideration());
    const ivNote = ivPricingConsideration(options);
    if (ivNote) considerations.push(ivNote);
  } else if (instrument === "long" || instrument === "short") {
    considerations.push(noExpirationConsideration(timeframe));
    if (instrument === "short") considerations.push(unlimitedShortLossConsideration());
    considerations.push(optionsAlternativeConsideration(instrument, timeframe, options));
  } else {
    // "future"
    considerations.push(futuresScopeConsideration());
  }

  const flagCount = considerations.filter((c) => c.tone === "flag").length;
  const flagLabels = considerations.filter((c) => c.tone === "flag").map((c) => c.label);
  const pricingClause = ivInformed
    ? `This read is grounded in ${ticker}'s real, current options pricing (Alpha Vantage, as of ${options.quoteDate ?? options.asOf}).`
    : `This read is structural/timeframe-based only — not informed by ${ticker}'s actual option pricing (options data status: ${options.status}).`;
  const summary =
    flagCount === 0
      ? `Nothing here flags a concrete mismatch between the ${instrument} chosen and the stated ${timeframe} timeframe. ` +
        `${pricingClause} This is not a recommendation on the instrument or the thesis — weigh it alongside your own sizing and risk tolerance.`
      : `${flagCount} thing${flagCount === 1 ? "" : "s"} worth weighing on the instrument choice itself, separate ` +
        `from Distresse's read on the thesis: ${flagLabels.join("; ")}. ${pricingClause} This is not a recommendation ` +
        `on the instrument or the thesis — weigh it alongside your own sizing and risk tolerance.`;

  const generatedBy = ivInformed
    ? `Instrument Fit · grounded in ${ticker}'s real ATM IV as of ${options.quoteDate ?? options.asOf}`
    : `Instrument Fit · structural/timeframe read only (options data: ${options.status})`;

  return {
    ticker,
    instrument,
    timeframe,
    catalystType,
    isOptionsInstrument,
    optionsStatus: options.status,
    ivInformed,
    considerations,
    summary,
    generatedBy,
  };
}
