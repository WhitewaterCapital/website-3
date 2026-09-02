import { ModuleNav } from "@/components/ModuleNav";
import { Card, Stat } from "@/components/ui";
import { members, contributions, snapshots } from "@/lib/sample-data";
import {
  ownershipByMember,
  currentUnitValue,
  totalUnits,
  latestValue,
  STARTING_UNIT_VALUE,
} from "@/lib/units";
import { usd, pct, num, shortDate } from "@/lib/format";

// MEMBERS PAGE — unit accounting. Who owns what, and why it's fair.
export default function MembersPage() {
  const value = latestValue(snapshots);
  const unitValue = currentUnitValue(contributions, value);
  const rows = ownershipByMember(members, contributions, value);
  const units = totalUnits(contributions);

  return (
    <div>
      <ModuleNav crumb="Ownership" />
      <main className="mx-auto max-w-5xl px-5 py-8">
        <h1 className="text-xl font-semibold">Members &amp; ownership</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Everyone owns <em>units</em>, like shares of a tiny fund. Contributions
          buy units at that day&apos;s unit value, so deposits at different times
          stay fair.
        </p>

        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pool value" value={usd(value)} />
          <Stat
            label="Unit value"
            value={usd(unitValue, { cents: true })}
            tone={unitValue >= STARTING_UNIT_VALUE ? "up" : "down"}
            sub={`from ${usd(STARTING_UNIT_VALUE, { cents: true })}`}
          />
          <Stat label="Units outstanding" value={num(units, 1)} />
          <Stat label="Members" value={members.length} />
        </div>

        <Card title="Ownership">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-foreground/50">
                <th className="pb-2 font-medium">Member</th>
                <th className="pb-2 text-right font-medium">Units</th>
                <th className="pb-2 text-right font-medium">Contributed</th>
                <th className="pb-2 text-right font-medium">Value now</th>
                <th className="pb-2 text-right font-medium">Gain</th>
                <th className="pb-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.member.id}
                  className="border-t border-foreground/10"
                >
                  <td className="py-2 font-medium">
                    {r.member.name}
                    {r.member.role === "admin" && (
                      <span className="ml-2 text-xs text-foreground/40">
                        admin
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {num(r.units, 1)}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {usd(r.contributedUsd)}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {usd(r.currentValueUsd)}
                  </td>
                  <td
                    className={`py-2 text-right tabular-nums ${
                      r.gainUsd >= 0 ? "text-emerald-500" : "text-rose-500"
                    }`}
                  >
                    {usd(r.gainUsd)} ({pct(r.gainPct / 100)})
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {r.ownershipPct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Contribution history">
          <ul className="space-y-2 text-sm">
            {contributions
              .slice()
              .reverse()
              .map((c) => {
                const who = members.find((m) => m.id === c.memberId)?.name ?? "—";
                return (
                  <li
                    key={c.id}
                    className="flex items-center justify-between border-t border-foreground/10 py-2 first:border-0"
                  >
                    <span>
                      <span className="font-medium">{who}</span>{" "}
                      <span className="text-foreground/50">
                        {c.note ? `· ${c.note}` : ""}
                      </span>
                    </span>
                    <span className="flex items-center gap-4 tabular-nums">
                      <span className="text-foreground/50">
                        {num(c.unitsIssued, 1)} units
                      </span>
                      <span className="font-medium">{usd(c.amountUsd)}</span>
                      <span className="text-xs text-foreground/40">
                        {shortDate(c.date)}
                      </span>
                    </span>
                  </li>
                );
              })}
          </ul>
        </Card>
      </main>
    </div>
  );
}
