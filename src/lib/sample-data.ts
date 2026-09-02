import type {
  Member,
  Contribution,
  Snapshot,
  Position,
  Proposal,
  Trade,
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
