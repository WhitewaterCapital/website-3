import type { Contribution, Member, Snapshot } from "./types";

// ---------------------------------------------------------------------------
// Unit accounting — the fair way to share one pool of capital.
//
// Everyone owns "units", like shares of a tiny mutual fund. When you contribute
// money you buy units at that day's unit value:
//
//     unitValue = totalAccountValue / totalUnitsOutstanding
//     unitsIssued = amountContributed / unitValue
//
// Because value is tracked in units, deposits and withdrawals at different times
// are always fair: nobody's later top-up dilutes an earlier member's gains.
// Starting unit value is $10.00 by convention.
// ---------------------------------------------------------------------------

export const STARTING_UNIT_VALUE = 10;

export type MemberOwnership = {
  member: Member;
  units: number;
  contributedUsd: number;
  currentValueUsd: number;
  ownershipPct: number;
  gainUsd: number;
  gainPct: number;
};

export function totalUnits(contributions: Contribution[]): number {
  return contributions.reduce((sum, c) => sum + c.unitsIssued, 0);
}

// Current $/unit given the latest account value.
export function currentUnitValue(
  contributions: Contribution[],
  latestValueUsd: number,
): number {
  const units = totalUnits(contributions);
  return units > 0 ? latestValueUsd / units : STARTING_UNIT_VALUE;
}

// Break the pool down per member: how many units they hold, what that's worth
// now, and their gain.
export function ownershipByMember(
  members: Member[],
  contributions: Contribution[],
  latestValueUsd: number,
): MemberOwnership[] {
  const allUnits = totalUnits(contributions);
  const unitValue = currentUnitValue(contributions, latestValueUsd);

  return members
    .map((member) => {
      const mine = contributions.filter((c) => c.memberId === member.id);
      const units = mine.reduce((s, c) => s + c.unitsIssued, 0);
      const contributedUsd = mine.reduce((s, c) => s + c.amountUsd, 0);
      const currentValueUsd = units * unitValue;
      const gainUsd = currentValueUsd - contributedUsd;
      return {
        member,
        units,
        contributedUsd,
        currentValueUsd,
        ownershipPct: allUnits > 0 ? (units / allUnits) * 100 : 0,
        gainUsd,
        gainPct: contributedUsd > 0 ? (gainUsd / contributedUsd) * 100 : 0,
      };
    })
    .sort((a, b) => b.currentValueUsd - a.currentValueUsd);
}

// What one new dollar buys today — handy for the "add contribution" flow.
export function unitsForAmount(
  contributions: Contribution[],
  latestValueUsd: number,
  amountUsd: number,
): number {
  const uv = currentUnitValue(contributions, latestValueUsd);
  return amountUsd / uv;
}

export function latestValue(snapshots: Snapshot[]): number {
  return snapshots.length ? snapshots[snapshots.length - 1].totalValueUsd : 0;
}
