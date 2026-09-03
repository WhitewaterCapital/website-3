import type {
  Member,
  Contribution,
  Snapshot,
  Position,
  Proposal,
  Trade,
  PositionEntryContext,
} from "./types";

// ---------------------------------------------------------------------------
// Sample data. This is what the app renders until a real broker + DB are wired
// in. Everything here comes from ONE deterministic simulation so the numbers
// reconcile: contributions flow into the pool, performance is measured on unit
// value (contribution-neutral), and the dashboard, public page, and members
// page all agree.
// ---------------------------------------------------------------------------

export const members: Member[] = [
  { id: "m_james", name: "James", email: "james@example.com", role: "admin", joinedAt: "2026-01-31" },
  { id: "m_alan", name: "Alan", email: "alan@example.com", role: "member", joinedAt: "2026-01-31" },
  { id: "m_jt", name: "JT", email: "jt@example.com", role: "member", joinedAt: "2026-01-31" },
  { id: "m_sam", name: "Sam", email: "sam@example.com", role: "member", joinedAt: "2026-01-31" },
  { id: "m_dana", name: "Dana", email: "dana@example.com", role: "member", joinedAt: "2026-03-14" },
];

// Deterministic PRNG (mulberry32) so charts are stable across reloads.
function makeRng(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Deposits that happen during the simulation, by week index. Units are issued
// at the unit value on that week (computed in the sim, not hardcoded).
const DEPOSITS: {
  week: number;
  memberId: string;
  amountUsd: number;
  note: string;
}[] = [
  { week: 0, memberId: "m_james", amountUsd: 6000, note: "Seed" },
  { week: 0, memberId: "m_alan", amountUsd: 5000, note: "Seed" },
  { week: 0, memberId: "m_jt", amountUsd: 4000, note: "Seed" },
  { week: 0, memberId: "m_sam", amountUsd: 5000, note: "Seed" },
  { week: 6, memberId: "m_dana", amountUsd: 4000, note: "Joined" },
  { week: 14, memberId: "m_james", amountUsd: 1000, note: "Top-up" },
];

const STARTING_UNIT_VALUE = 10;

function simulate() {
  const rng = makeRng(20260131);
  const start = new Date("2026-01-31T00:00:00Z");
  const weeks = 26;

  let unitValue = STARTING_UNIT_VALUE; // grows only with market performance
  let units = 0; // total units outstanding (grows with deposits)
  let spy = 560;

  const snaps: Snapshot[] = [];
  const contributions: Contribution[] = [];
  let cId = 1;

  for (let w = 0; w <= weeks; w++) {
    const d = new Date(start.getTime() + w * 7 * 24 * 3600 * 1000);

    // Market moves the unit value (not deposits). ~0.25%/wk drift + noise.
    if (w > 0) {
      const pRet = 0.0025 + (rng() - 0.5) * 0.022;
      const sRet = 0.0015 + (rng() - 0.5) * 0.018;
      unitValue *= 1 + pRet;
      spy *= 1 + sRet;
    }

    // Any deposits this week buy units at the current unit value.
    for (const dep of DEPOSITS.filter((x) => x.week === w)) {
      const issued = dep.amountUsd / unitValue;
      units += issued;
      contributions.push({
        id: `c${cId++}`,
        memberId: dep.memberId,
        date: d.toISOString().slice(0, 10),
        amountUsd: dep.amountUsd,
        unitsIssued: Math.round(issued * 100) / 100,
        note: dep.note,
      });
    }

    const totalValue = units * unitValue;
    const invested = totalValue * (0.6 + rng() * 0.3); // 60–90% invested
    snaps.push({
      date: d.toISOString().slice(0, 10),
      totalValueUsd: Math.round(totalValue),
      cashUsd: Math.round(totalValue - invested),
      investedUsd: Math.round(invested),
      unitValueUsd: Math.round(unitValue * 1000) / 1000,
      spyPrice: Math.round(spy * 100) / 100,
    });
  }

  return { snaps, contributions };
}

const sim = simulate();

export const snapshots: Snapshot[] = sim.snaps;
export const contributions: Contribution[] = sim.contributions;

export const positions: Position[] = [
  { symbol: "NVDA", quantity: 36, avgCostUsd: 118.4, lastPriceUsd: 141.2, marketValueUsd: 5083.2, unrealizedPnlUsd: 820.8, openedAt: "2026-03-02" },
  { symbol: "MSFT", quantity: 12, avgCostUsd: 402.1, lastPriceUsd: 438.9, marketValueUsd: 5266.8, unrealizedPnlUsd: 441.6, openedAt: "2026-02-20" },
  { symbol: "COST", quantity: 6, avgCostUsd: 872.0, lastPriceUsd: 905.3, marketValueUsd: 5431.8, unrealizedPnlUsd: 199.8, openedAt: "2026-04-11" },
  { symbol: "AMD", quantity: 27, avgCostUsd: 154.7, lastPriceUsd: 149.1, marketValueUsd: 4025.7, unrealizedPnlUsd: -151.2, openedAt: "2026-05-01" },
];

export const proposals: Proposal[] = [
  {
    id: "p1",
    symbol: "GOOGL",
    side: "buy",
    targetUsd: 1500,
    thesis: "Cloud growth reaccelerating and Gemini traction; trading below peers on forward earnings. Entry on the recent pullback.",
    proposedBy: "m_alan",
    createdAt: "2026-07-28T15:04:00Z",
    status: "open",
    votes: [
      { memberId: "m_alan", value: "yes", at: "2026-07-28T15:04:00Z" },
      { memberId: "m_james", value: "yes", at: "2026-07-28T18:20:00Z" },
    ],
  },
  {
    id: "p2",
    symbol: "AMD",
    side: "sell",
    targetUsd: 1341,
    thesis: "Thesis broke — losing share in the segment we bought it for. Cut the loss and redeploy.",
    proposedBy: "m_jt",
    createdAt: "2026-07-30T13:10:00Z",
    status: "open",
    votes: [{ memberId: "m_jt", value: "yes", at: "2026-07-30T13:10:00Z" }],
  },
];

export const trades: Trade[] = [
  { id: "t1", symbol: "MSFT", side: "buy", quantity: 4, priceUsd: 402.1, executedAt: "2026-02-20T14:35:00Z" },
  { id: "t2", symbol: "NVDA", side: "buy", quantity: 12, priceUsd: 118.4, executedAt: "2026-03-02T15:02:00Z" },
  { id: "t3", symbol: "COST", side: "buy", quantity: 2, priceUsd: 872.0, executedAt: "2026-04-11T16:11:00Z" },
  { id: "t4", symbol: "AMD", side: "buy", quantity: 9, priceUsd: 154.7, executedAt: "2026-05-01T14:20:00Z" },
];

// ---------------------------------------------------------------------------
// IMP-01 — per-strategy performance attribution. ADDITIVE ONLY (nothing above
// this line is changed). There is no real multi-strategy ledger anywhere in
// this codebase — `account`/`snapshots` above is ONE blended book. This is a
// clearly-labeled SYNTHETIC, illustrative decomposition of that same book's
// actual weekly unit-value return into three lines that a real desk would
// track separately and NEVER blend: discretionary, model-driven, and paper
// (paper trades no real capital). Built deterministically (the same
// mulberry32 PRNG pattern as the account sim above, a different seed) so it
// roughly reconciles with the real blended weekly return, but the split
// itself is illustrative — not a real attribution ledger. The performance
// page must show a SAMPLE DATA banner wherever this is rendered.
// ---------------------------------------------------------------------------

export type StrategyKind = "discretionary" | "model-driven" | "paper";

export type StrategyMeta = {
  id: string;
  name: string;
  kind: StrategyKind;
  description: string;
};

export const strategies: StrategyMeta[] = [
  {
    id: "core",
    name: "Core conviction picks",
    kind: "discretionary",
    description: "The four-rule concentrated book members vote on — the same account tracked elsewhere on the desk.",
  },
  {
    id: "signals",
    name: "Incepta + Aurora signals",
    kind: "model-driven",
    description: "Sized off the equity + macro engines' output; not yet a capital-segregated sleeve.",
  },
  {
    id: "paper-weekly",
    name: "WW-WEEKLY rank (paper)",
    kind: "paper",
    description: "Tracked in a paper book only — no real capital committed while it accrues a live track record.",
  },
];

export type StrategyAttributionPoint = {
  date: string; // ISO date, aligned with `snapshots`
  weight: Record<string, number>; // strategy id -> fraction of the book that week (paper is always 0 — it carries no real capital by definition)
  contributionPct: Record<string, number>; // strategy id -> contribution to that week's return, in percentage points
};

export const strategyAttribution: StrategyAttributionPoint[] = (() => {
  // A different seed from the account sim above: this is an independent
  // illustrative split, not derived from any real per-trade record.
  const rng = makeRng(20260201);
  return snapshots.map((s, i) => {
    if (i === 0) {
      return {
        date: s.date,
        weight: { core: 0.6, signals: 0.25, "paper-weekly": 0 },
        contributionPct: { core: 0, signals: 0, "paper-weekly": 0 },
      };
    }
    const weekReturnPct = (s.unitValueUsd / snapshots[i - 1].unitValueUsd - 1) * 100;
    // Split the week's real blended return across the two capital-bearing
    // sleeves with a small persistent tilt + noise; paper gets its own
    // shadow return that never touches the real blended number.
    const coreShare = 0.55 + (rng() - 0.5) * 0.25;
    const signalsShare = 1 - coreShare;
    const paperShadowPct = weekReturnPct * (0.6 + rng() * 0.8) + (rng() - 0.5) * 0.4;
    return {
      date: s.date,
      weight: {
        core: Math.round((0.55 + (rng() - 0.5) * 0.1) * 100) / 100,
        signals: Math.round((0.28 + (rng() - 0.5) * 0.08) * 100) / 100,
        "paper-weekly": 0,
      },
      contributionPct: {
        core: Math.round(weekReturnPct * coreShare * 100) / 100,
        signals: Math.round(weekReturnPct * signalsShare * 100) / 100,
        "paper-weekly": Math.round(paperShadowPct * 100) / 100,
      },
    };
  });
})();

// ---------------------------------------------------------------------------
// IMP-01 — v1.0 performance disclosures. Every value is grounded in facts
// already true of this sample simulation (inception = the sim's own start
// date, benchmark = the SPY series already carried on every Snapshot,
// valuation cadence = the sim's own weekly step, cash-flow treatment =
// src/lib/units.ts's unit accounting) — nothing here is invented for this page.
// ---------------------------------------------------------------------------
export const performanceDisclosures = {
  inceptionDate: snapshots[0]?.date ?? "—",
  benchmark: "S&P 500 (tracked via SPY close — see Snapshot.spyPrice)",
  feeTreatment:
    "Returns shown are GROSS — this simulation has no management or performance fee schedule implemented.",
  cashFlowTreatment:
    "Unit accounting (src/lib/units.ts): every deposit/withdrawal buys or redeems units at that day's unit value, so cash-flow timing never dilutes or inflates another member's return.",
  valuationTiming: "Valued weekly, as of each snapshot's date — this sample simulation's own cadence.",
  dataSource:
    "Illustrative synthetic sample data (src/lib/sample-data.ts) — no live broker feed or real multi-strategy ledger is connected in this environment.",
};

// ---------------------------------------------------------------------------
// WW-WATCH / IMP-04 — hand-authored "as of entry" snapshots for the four
// sample positions above, keyed by symbol.
//
// This is NOT captured from any real ledger — none exists (see
// PositionEntryContext's own comment in src/lib/types.ts). It's SAMPLE data
// standing in for one, deliberately authored independently of what a live
// call to Distresse/Intra-Exitus produces today for these same tickers —
// those are deterministic, time-invariant demo functions of ticker+instrument
// (see src/lib/models/impl/distresse.ts), so re-running them never drifts on
// their own. Any "forecast changed since entry" the watch checks surface for
// these four positions comes from this hand-authored snapshot genuinely
// differing from that fixed live output — which is exactly what lets
// WATCH-01's drift check be demonstrated honestly without a real history
// store. AMD's snapshot in particular was authored to line up with the
// existing AMD sell proposal in `proposals` above ("Thesis broke...") — a
// deliberately large conviction drop, not a coincidence.
// ---------------------------------------------------------------------------
export const positionEntryContext: Record<string, PositionEntryContext> = {
  NVDA: {
    symbol: "NVDA",
    originatingStrategy: "Distresse + Intra / Exitus",
    weightAtEntryPct: 8.5,
    entryScoreSnapshot: {
      rating: "go",
      conviction: 74,
      regime: "Disinflationary soft-landing, momentum-led tape",
    },
    forecastAtEntry: { bias: "long", entryZone: [112, 119], stop: 104, targets: [128, 138, 150] },
    decisionNote: "AI capex cycle intact; entered on the pullback into the demand shelf.",
    decidedAt: "2026-03-02T15:00:00Z",
    generatedBy: "Watch ledger (sample)",
  },
  MSFT: {
    symbol: "MSFT",
    originatingStrategy: "Distresse + Intra / Exitus",
    weightAtEntryPct: 9.1,
    entryScoreSnapshot: {
      rating: "go",
      conviction: 68,
      regime: "Late-cycle, easing bias, dispersion rising",
    },
    forecastAtEntry: { bias: "long", entryZone: [396, 405], stop: 378, targets: [420, 438, 455] },
    decisionNote: "Azure growth reacceleration thesis; core compounder allocation.",
    decidedAt: "2026-02-20T14:30:00Z",
    generatedBy: "Watch ledger (sample)",
  },
  COST: {
    symbol: "COST",
    originatingStrategy: "Distresse + Intra / Exitus",
    weightAtEntryPct: 9.4,
    entryScoreSnapshot: {
      rating: "conditional",
      conviction: 55,
      regime: "Slowing growth, sticky rates, defensive rotation",
    },
    forecastAtEntry: { bias: "long", entryZone: [858, 875], stop: 820, targets: [910, 945, 980] },
    decisionNote: "Defensive membership-model quality at a full price; sized down for that.",
    decidedAt: "2026-04-11T16:00:00Z",
    generatedBy: "Watch ledger (sample)",
  },
  AMD: {
    symbol: "AMD",
    originatingStrategy: "Distresse + Intra / Exitus",
    weightAtEntryPct: 7.0,
    entryScoreSnapshot: {
      rating: "go",
      conviction: 82,
      regime: "Disinflationary soft-landing, momentum-led tape",
    },
    forecastAtEntry: { bias: "long", entryZone: [149, 156], stop: 140, targets: [168, 182, 198] },
    decisionNote: "Data-center GPU share-gain thesis vs. NVDA — since challenged (see proposal p2: thesis broke).",
    decidedAt: "2026-05-01T14:15:00Z",
    generatedBy: "Watch ledger (sample)",
  },
};
