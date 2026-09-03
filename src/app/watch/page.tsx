import Link from "next/link";
import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { positions, positionEntryContext } from "@/lib/sample-data";
import { usd, shortDate } from "@/lib/format";
import { models } from "@/lib/models/registry";
import type { Position } from "@/lib/types";
import type { EntryExitPlan, StressVerdict } from "@/lib/models/types";
import { getGraphExport } from "@/lib/graph";
import { getWeeklyExport } from "@/lib/weekly";
import { getStateExport } from "@/lib/state";
import { runChecks, type PositionCheck, type CheckSeverity } from "@/lib/watch/checks";
import { computeUrgency, logUrgencyPrediction, listScoreHistory, type UrgencyResult } from "@/lib/watch/urgency";
import { buildDailyDigest } from "@/lib/watch/slack";
import { can, listAudit, appendAudit, type Role } from "@/lib/watch/roles";

// WW-WATCH — the position monitor (WATCH-01/02/03) + IMP-04's position detail
// view, combined into one page: with only four sample positions, a single
// screen reads better than a hub + four separate detail routes. Everything on
// this page is server-rendered from real (if synthetic-demo, where noted)
// inputs — see src/lib/watch/checks.ts for exactly which checks are backed by
// real engine data today vs. honestly marked unavailable.
export const dynamic = "force-dynamic"; // always read the latest engine exports + recompute live model calls

const SEVERITY_TONE: Record<CheckSeverity, "up" | "down" | "warn" | "neutral"> = {
  ok: "up",
  warn: "warn",
  alert: "down",
  info: "neutral",
};

// A small, one-time (per server process) illustrative seed for IMP-03's audit
// log, so the page has something real to show without growing on every
// request. A real system would populate this from actual privileged actions,
// not a page load.
let auditSeeded = false;
function seedAuditOnce() {
  if (auditSeeded || listAudit().length > 0) {
    auditSeeded = true;
    return;
  }
  appendAudit({
    who: "dana@example.com",
    role: "research-operator",
    action: "shadow-run-model",
    before: { status: "untested" },
    after: { status: "shadow" },
    reason: "Weekly review: shadow-running the refreshed WW-WEEKLY ridge model before any promotion discussion.",
  });
  appendAudit({
    who: "james@example.com",
    role: "risk-approver",
    action: "change-allocator-cap",
    before: { maxSingleNamePct: 25 },
    after: { maxSingleNamePct: 20 },
    reason: "Tightening single-name cap after the NVDA/AMD sector-overlap flag on the position monitor.",
  });
  auditSeeded = true;
}

export default async function WatchPage() {
  seedAuditOnce();

  const [graphExport, weeklyExport, stateExport] = await Promise.all([
    getGraphExport(),
    getWeeklyExport(),
    getStateExport(),
  ]);

  const results = await Promise.all(
    positions.map(async (position) => {
      const idea = {
        ticker: position.symbol,
        instrument: "long" as const,
        thesis: positionEntryContext[position.symbol]?.decisionNote ?? "",
      };
      const [verdict, plan] = await Promise.all([
        models.distresse.evaluate(idea),
        models.intraExitus.plan(idea),
      ]);
      const check = runChecks(position, plan, verdict, graphExport, weeklyExport, stateExport, {
        entryContext: positionEntryContext[position.symbol],
        book: positions,
      });
      const urgency = computeUrgency(check);
      logUrgencyPrediction(position.symbol, urgency, check.asOf);
      return { position, verdict, plan, check, urgency };
    }),
  );

  const urgencyBySymbol = new Map(results.map((r) => [r.position.symbol, r.urgency]));
  const digest = buildDailyDigest(
    results.map((r) => r.check),
    urgencyBySymbol,
  );

  const demoRole: Role = "research-operator"; // illustrative only — see roles.ts header comment; no real per-user identity exists

  return (
    <div>
      <ModuleNav crumb="Watch" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// WW-WATCH</p>
          <span className="font-mono text-xs text-muted">the position monitor</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Don&apos;t just enter a trade. Watch it.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Every open position, checked against its own invalidation conditions, its stated horizon, how its
          originating models&apos; read has moved since entry, and the book around it. Nothing below is
          fabricated — a check that has no real data behind it says so, instead of guessing.
        </p>

        <div className="mt-8 space-y-6">
          {results.map(({ position, verdict, plan, check, urgency }) => (
            <PositionCard key={position.symbol} position={position} verdict={verdict} plan={plan} check={check} urgency={urgency} />
          ))}
        </div>

        <div className="mt-10 grid gap-6 lg:grid-cols-2">
          <Card title="Sample daily digest (WATCH-03)">
            <p className="mb-3 text-xs text-muted">
              What <code className="text-foreground/80">buildDailyDigest()</code> produces from the checks above —
              this is the message a <code className="text-foreground/80">Notifier</code> (ConsoleNotifier in dev,
              SlackWebhookNotifier once <code className="text-foreground/80">SLACK_WEBHOOK_URL</code> is set) would
              deliver. Nothing is actually sent from this page.
            </p>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap border border-hairline bg-background p-3 text-xs">
              {digest}
            </pre>
          </Card>

          <Card title="Score the scorer (WATCH-02)">
            <p className="mb-3 text-xs text-muted">
              Every urgency read above was just logged via{" "}
              <code className="text-foreground/80">logUrgencyPrediction()</code>. This is an in-memory array today
              (see urgency.ts) — it needs a real DB table before it survives a restart — but the mechanism is real:
              log the predicted range, and once the week plays out, reconcile it against what actually happened.
            </p>
            <ul className="space-y-2 text-xs">
              {listScoreHistory()
                .slice(-4)
                .map((e, i) => (
                  <li key={i} className="border-t border-hairline pt-2">
                    <span className="font-medium">{e.symbol}</span> — predicted [{e.expectedRangeLow.toFixed(2)},{" "}
                    {e.expectedRangeHigh.toFixed(2)}] as of {shortDate(e.asOf)}.{" "}
                    {e.realisedPriceUsd == null
                      ? "Not yet reconciled."
                      : `Realised ${e.realisedPriceUsd.toFixed(2)} — ${e.withinPredictedRange ? "within range" : "outside range"}.`}
                  </li>
                ))}
            </ul>
          </Card>
        </div>

        <div className="mt-6">
          <RolesAndAudit demoRole={demoRole} />
        </div>
      </main>
    </div>
  );
}

function PositionCard({
  position,
  verdict,
  plan,
  check,
  urgency,
}: {
  position: Position;
  verdict: StressVerdict;
  plan: EntryExitPlan;
  check: PositionCheck;
  urgency: UrgencyResult;
}) {
  const entry = positionEntryContext[position.symbol];
  const pnlTone = position.unrealizedPnlUsd >= 0 ? "up" : "down";
  const urgencyTone = urgency.band === "act-today" ? "down" : urgency.band === "act-this-week" ? "warn" : "up";

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold">{position.symbol}</span>
            <span className="text-sm text-foreground/50">
              {position.quantity} sh @ {usd(position.avgCostUsd, { cents: true })} avg
            </span>
          </div>
          <p className="mt-1 text-xs text-foreground/50">
            Opened {shortDate(position.openedAt)} · last {usd(position.lastPriceUsd, { cents: true })} ·{" "}
            <span className={pnlTone === "up" ? "text-emerald-500" : "text-rose-500"}>
              {position.unrealizedPnlUsd >= 0 ? "+" : ""}
              {usd(position.unrealizedPnlUsd)}
            </span>
          </p>
        </div>
        <div className="text-right">
          <Badge tone={urgencyTone}>{urgency.band}</Badge>
          <p className="mt-1 text-xs text-foreground/50">
            Expected range: {usd(urgency.expectedRangeLow, { cents: true })} – {usd(urgency.expectedRangeHigh, { cents: true })}
          </p>
        </div>
      </div>
      <p className="mt-2 text-xs text-foreground/60">{urgency.drivenBy}</p>

      {/* Originating strategy / entry context — IMP-04 */}
      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="eyebrow">Originating decision</h3>
        {entry ? (
          <div className="mt-2 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <p>
                <span className="text-foreground/50">Strategy:</span> {entry.originatingStrategy}
              </p>
              <p>
                <span className="text-foreground/50">Weight at entry:</span> {entry.weightAtEntryPct.toFixed(1)}% of book
              </p>
              <p>
                <span className="text-foreground/50">Entry score:</span> {entry.entryScoreSnapshot.rating} at{" "}
                {entry.entryScoreSnapshot.conviction} conviction
              </p>
              <p className="text-xs text-foreground/50">&ldquo;{entry.entryScoreSnapshot.regime}&rdquo;</p>
            </div>
            <div>
              <p className="text-foreground/70">{entry.decisionNote}</p>
              <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                ⚠ {entry.generatedBy} — hand-authored, not a real decision-ledger read (none exists in this codebase).
              </p>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-sm text-muted">No entry-time snapshot on file for this symbol.</p>
        )}
        <Link
          href={`/stress-test?ticker=${position.symbol}&instrument=long`}
          className="mt-2 inline-block text-xs text-accent hover:underline"
        >
          Open in Strictus Testum (illustrative decision-ledger link — the ticker isn&apos;t actually prefilled yet) →
        </Link>
      </div>

      {/* Forecast + horizon */}
      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="eyebrow">Forecast + horizon (live)</h3>
        <div className="mt-2 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <p>
              <span className="text-foreground/50">Distresse:</span> {verdict.rating} at {verdict.conviction} conviction
            </p>
            <p className="text-xs text-foreground/50">&ldquo;{verdict.regime}&rdquo;</p>
            {verdict.generatedBy.toLowerCase().includes("sample") && (
              <p className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">⚠ SAMPLE — {verdict.generatedBy}</p>
            )}
          </div>
          <div>
            <p>
              <span className="text-foreground/50">Intra/Exitus:</span> {plan.bias} · stop{" "}
              {Number.isNaN(plan.stop) ? "—" : usd(plan.stop, { cents: true })} · targets{" "}
              {plan.targets.length ? plan.targets.map((t) => usd(t, { cents: true })).join(", ") : "—"}
            </p>
            <p className="text-xs text-foreground/50">{plan.timeStop}</p>
            <p className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">⚠ {plan.generatedBy}</p>
          </div>
        </div>
      </div>

      {/* WATCH-01 checks */}
      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="eyebrow">Checks</h3>
        <ul className="mt-2 space-y-2">
          {check.checks.map((c) => (
            <li key={c.id} className="flex items-start gap-3 text-sm">
              <Badge tone={c.available ? SEVERITY_TONE[c.severity] : "neutral"}>
                {c.available ? c.severity : "n/a"}
              </Badge>
              <div>
                <p className="font-medium">{c.label}</p>
                <p className="text-xs text-foreground/60">{c.available ? c.detail : c.reason}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function RolesAndAudit({ demoRole }: { demoRole: Role }) {
  const actions = ["retrain-model", "shadow-run-model", "read-card", "promote-to-live", "demote-from-live", "change-allocator-cap", "trip-kill-switch"] as const;
  const roles: Role[] = ["research-operator", "risk-approver"];
  const audit = listAudit();

  return (
    <Card title="Roles & audit (IMP-03 — illustrative)">
      <p className="text-xs text-muted">
        This repo has one shared passcode for the whole site (src/lib/auth.ts) — there are no real per-user roles
        or sessions yet. The table and log below are <code className="text-foreground/80">src/lib/watch/roles.ts</code>&apos;s
        policy logic exercised directly, standing in for a real auth-gated promotion UI. Signed in here as (illustrative):{" "}
        <span className="font-medium text-foreground">{demoRole}</span>.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="pb-2 pr-4 font-medium">Action</th>
              {roles.map((r) => (
                <th key={r} className="pb-2 pr-4 font-medium">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a} className="border-t border-hairline">
                <td className="py-1.5 pr-4">{a}</td>
                {roles.map((r) => (
                  <td key={r} className="py-1.5 pr-4">
                    {can(a, r) ? "✓" : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">
        Promotion to live sizing also needs two DISTINCT people (see <code className="text-foreground/80">canFinalizePromotion</code>)
        — a risk-approver cannot finalize their own promotion request.
      </p>

      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="eyebrow">Recent audit entries (in-memory demo)</h3>
        <ul className="mt-2 space-y-2 text-xs">
          {audit.map((e) => (
            <li key={e.id} className="border-t border-hairline pt-2 first:border-t-0 first:pt-0">
              <span className="font-medium">{e.who}</span> ({e.role}) — {e.action} at {shortDate(e.at)}
              <p className="text-foreground/60">{e.reason}</p>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
