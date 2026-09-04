"use client";

// The daily digest, as a real UI instead of a raw <pre> text dump. Same
// inputs buildDailyDigest() (src/lib/watch/slack.ts) formats into a plain
// string for a Slack notifier — this renders the identical information as
// severity badges, a per-position list, and honest "unavailable" counts, so
// a person reading it on the page doesn't have to parse a monospace block.
// The raw text is still available (collapsed) underneath, since that string
// is exactly what a real Notifier would actually send — worth keeping visible
// for anyone checking the two match.

import { useState } from "react";
import { Card, Badge } from "@/components/ui";
import type { PositionCheck, CheckSeverity } from "@/lib/watch/checks";
import type { UrgencyResult } from "@/lib/watch/urgency";

const SEVERITY_TONE: Record<CheckSeverity, "up" | "down" | "warn" | "neutral"> = {
  ok: "up",
  info: "neutral",
  warn: "warn",
  alert: "down",
};

function worstSeverity(check: PositionCheck): CheckSeverity {
  const rank: Record<CheckSeverity, number> = { ok: 0, info: 1, warn: 2, alert: 3 };
  return check.checks
    .filter((c) => c.available)
    .reduce<CheckSeverity>((acc, c) => (rank[c.severity] > rank[acc] ? c.severity : acc), "ok");
}

const urgencyTone = (band: UrgencyResult["band"] | undefined) =>
  band === "act-today" ? "down" : band === "act-this-week" ? "warn" : "neutral";

export function DigestPanel({
  positionChecks,
  urgencies,
  rawText,
}: {
  positionChecks: PositionCheck[];
  urgencies: Map<string, UrgencyResult>;
  /** The exact string buildDailyDigest() produced from the same inputs — shown collapsed, for parity checking. */
  rawText: string;
}) {
  const [showRaw, setShowRaw] = useState(false);

  return (
    <Card title="Daily Digest (WATCH-03)">
      <p className="mb-4 text-xs text-muted">
        What a <code className="text-foreground/80">Notifier</code> (ConsoleNotifier in dev,
        SlackWebhookNotifier once <code className="text-foreground/80">SLACK_WEBHOOK_URL</code> is set) would
        deliver, read as a list instead of a raw message string. Nothing is actually sent from this page.
      </p>

      {positionChecks.length === 0 ? (
        <p className="text-sm text-muted">No open positions to report on.</p>
      ) : (
        <ul className="space-y-4">
          {positionChecks.map((pc) => {
            const worst = worstSeverity(pc);
            const urgency = urgencies.get(pc.symbol);
            const tripped = pc.checks.filter((c) => c.available && c.severity !== "ok" && c.severity !== "info");
            const unavailable = pc.checks.filter((c) => !c.available).length;
            return (
              <li key={pc.symbol} className="border-t border-hairline pt-4 first:border-t-0 first:pt-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={SEVERITY_TONE[worst]}>{worst}</Badge>
                  <span className="font-semibold">{pc.symbol}</span>
                  <span className="text-xs text-muted">·</span>
                  <Badge tone={urgencyTone(urgency?.band)}>{urgency ? urgency.band : "urgency n/a"}</Badge>
                </div>

                {tripped.length === 0 ? (
                  <p className="mt-2 text-sm text-muted">No checks flagged.</p>
                ) : (
                  <ul className="mt-2 space-y-1.5">
                    {tripped.map((c) => (
                      <li key={c.id} className="flex items-start gap-2 text-sm">
                        <Badge tone={SEVERITY_TONE[c.severity]}>{c.severity}</Badge>
                        <span className="text-foreground/80">
                          <span className="font-medium">{c.label}:</span> {c.detail}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {unavailable > 0 && (
                  <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                    ⚠ {unavailable} check{unavailable === 1 ? "" : "s"} unavailable — silence there means &quot;no
                    data,&quot; not &quot;checked and fine.&quot; See the position card above for reasons.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <button
        onClick={() => setShowRaw((v) => !v)}
        className="mt-5 text-xs font-medium text-accent hover:underline"
      >
        {showRaw ? "Hide" : "Show"} the exact text a notifier would send →
      </button>
      {showRaw && (
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap border border-hairline bg-background p-3 text-xs">
          {rawText}
        </pre>
      )}
    </Card>
  );
}
