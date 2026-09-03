import type { PositionCheck, CheckSeverity } from "./checks";
import type { UrgencyResult, ScoreHistoryEntry } from "./urgency";

// ═══════════════════════════════════════════════════════════════════════════
// WATCH-03 — the alert layer. Pluggable notifier + severity routing + dedup +
// digest formatters. No real Slack workspace is wired in anywhere in this
// codebase or its environment — everything here is genuinely functional
// (ConsoleNotifier really logs; the dedup/rate-limit gate really gates; the
// digest builders really build real strings from real PositionCheck data) up
// to the point where a real network call to Slack would be required, which is
// exactly the seam SlackWebhookNotifier marks.
//
// Core philosophy, straight from the doc: "if the check job fails or the data
// is stale, Slack gets told the check did not run... silence has to mean
// checked and fine, never mean broken." Every notifier here either sends or
// throws — nothing swallows a failure into a silent no-op.
// ═══════════════════════════════════════════════════════════════════════════

export type AlertSeverity = "low" | "medium" | "high" | "critical";

export interface SlackAlert {
  symbol: string;
  threadKey: string; // one thread per position — e.g. "position:NVDA". No real Slack thread_ts exists here; this is the field a real integration would key its thread off of.
  severity: AlertSeverity;
  checkId: string; // which CheckResult.id triggered this — the dedup key's other half
  title: string;
  body: string;
  asOf: string;
}

export interface Notifier {
  send(alert: SlackAlert): Promise<void>;
}

// ─── Console notifier — genuinely functional, for dev/demo ────────────────

export class ConsoleNotifier implements Notifier {
  async send(alert: SlackAlert): Promise<void> {
    const stamp = new Date().toISOString();
    // eslint-disable-next-line no-console
    console.log(
      `[watch:slack:${alert.severity}] ${stamp} thread=${alert.threadKey} check=${alert.checkId} — ${alert.title}\n  ${alert.body}`,
    );
  }
}

// ─── Slack webhook notifier — stub that either really sends or throws ─────
//
// Reads SLACK_WEBHOOK_URL at call time (not at module load) so it behaves
// correctly however/whenever env vars are injected. When unset, this THROWS
// rather than silently doing nothing — per the doc's own "silence must mean
// checked and fine, never broken" rule, a notifier that cannot send has to
// say so loudly, at the call site, not swallow it.
export class SlackWebhookNotifier implements Notifier {
  async send(alert: SlackAlert): Promise<void> {
    const url = process.env.SLACK_WEBHOOK_URL;
    if (!url) {
      throw new Error(
        "SlackWebhookNotifier is not configured: SLACK_WEBHOOK_URL is not set. " +
          "Set it to a real Slack incoming-webhook URL, or use ConsoleNotifier for local/dev runs. " +
          "Do not catch and ignore this error — an alert that silently failed to send is exactly the 'broken' state the check system must never present as 'fine'.",
      );
    }
    const behavior = severityBehavior(alert.severity);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text:
          `${behavior.mentionAll ? "@channel " : behavior.mentionOwner ? "@here " : ""}` +
          `*[${alert.severity.toUpperCase()}] ${alert.title}*\n${alert.body}`,
        // A real integration would map threadKey -> a stored Slack thread_ts
        // for this position and reply into it; there is no such mapping here.
        thread_key: alert.threadKey,
      }),
    });
    if (!res.ok) {
      throw new Error(`SlackWebhookNotifier: webhook POST failed with ${res.status} ${res.statusText}.`);
    }
  }
}

// ─── Severity behavior — the doc's exact per-severity routing rules ───────

export interface SeverityBehavior {
  channelPost: boolean; // post to the channel now, vs. hold for the daily digest only
  mentionOwner: boolean;
  mentionAll: boolean;
  repeatUntilAcked: boolean;
}

export function severityBehavior(severity: AlertSeverity): SeverityBehavior {
  switch (severity) {
    case "low":
      return { channelPost: false, mentionOwner: false, mentionAll: false, repeatUntilAcked: false }; // digest-only
    case "medium":
      return { channelPost: true, mentionOwner: false, mentionAll: false, repeatUntilAcked: false }; // channel post
    case "high":
      return { channelPost: true, mentionOwner: true, mentionAll: false, repeatUntilAcked: false }; // mention owner
    case "critical":
      return { channelPost: true, mentionOwner: true, mentionAll: true, repeatUntilAcked: true }; // mention-all-and-repeat
  }
}

// Maps a CheckResult severity (checks.ts) onto an AlertSeverity, so a caller
// building SlackAlerts from a PositionCheck doesn't have to invent its own
// mapping. Not wired into any call site here — the position-monitor page
// (src/app/watch/page.tsx) shows the digest formatters below, not a live
// per-check notifier pipeline — but this is the correct, ready-to-use gate
// for whatever background job eventually calls Notifier.send for real.
export function checkSeverityToAlertSeverity(sev: CheckSeverity): AlertSeverity {
  switch (sev) {
    case "alert":
      return "critical";
    case "warn":
      return "high";
    case "info":
      return "medium";
    case "ok":
    default:
      return "low";
  }
}

// ─── Dedup / rate-limit gate ────────────────────────────────────────────
//
// "Same condition + same name inside a cooldown window doesn't re-alert."
// Injectable clock so this is testable without real wall-clock waits.
export interface Clock {
  now(): number;
}
export const systemClock: Clock = { now: () => Date.now() };

export class AlertGate {
  private lastSentAtMs = new Map<string, number>();

  constructor(
    private readonly cooldownMs: number,
    private readonly clock: Clock = systemClock,
  ) {}

  private key(symbol: string, checkId: string): string {
    return `${symbol}::${checkId}`;
  }

  // true => suppress (already alerted on this exact symbol+check within the cooldown window)
  shouldSuppress(symbol: string, checkId: string): boolean {
    const last = this.lastSentAtMs.get(this.key(symbol, checkId));
    if (last == null) return false;
    return this.clock.now() - last < this.cooldownMs;
  }

  markSent(symbol: string, checkId: string): void {
    this.lastSentAtMs.set(this.key(symbol, checkId), this.clock.now());
  }

  // For inspection/testing — never mutated by callers.
  snapshot(): ReadonlyMap<string, number> {
    return new Map(this.lastSentAtMs);
  }
}

// ─── Market-wide collapse rule ─────────────────────────────────────────────
//
// "Collapse >N simultaneous alerts into one market-wide alert" — if enough
// positions trip a check at the same moment, that is far more likely to be
// one market-wide move than N independent stories, and N separate pings just
// trains people to ignore the channel.
export const MARKET_WIDE_COLLAPSE_THRESHOLD = 5;

const ALERT_SEVERITY_RANK: Record<AlertSeverity, number> = { low: 0, medium: 1, high: 2, critical: 3 };

export function collapseIfMarketWide(alerts: SlackAlert[], threshold: number = MARKET_WIDE_COLLAPSE_THRESHOLD): SlackAlert[] {
  if (alerts.length <= threshold) return alerts;

  const worst = alerts.reduce<AlertSeverity>(
    (acc, a) => (ALERT_SEVERITY_RANK[a.severity] > ALERT_SEVERITY_RANK[acc] ? a.severity : acc),
    "low",
  );
  const symbols = Array.from(new Set(alerts.map((a) => a.symbol)));

  const collapsed: SlackAlert = {
    symbol: "MARKET",
    threadKey: "market-wide",
    severity: worst,
    checkId: "market-wide-collapse",
    title: `${alerts.length} positions triggered checks at once`,
    body: `More than ${threshold} positions tripped a check simultaneously (${symbols.join(", ")}) — treating this as a likely market-wide move rather than ${alerts.length} independent per-position stories. See the daily digest for the full per-position detail.`,
    asOf: alerts[0]?.asOf ?? new Date().toISOString(),
  };
  return [collapsed];
}

// ─────────────────────────────────────────────────────────────────────────
// Digest formatters — pure functions, no I/O. What buildDailyDigest and
// buildWeeklyDigest produce is plain text; a real Slack integration would
// post it via Notifier.send in one message rather than per-check pings.
// ─────────────────────────────────────────────────────────────────────────

function worstSeverity(check: PositionCheck): CheckSeverity {
  const rank: Record<CheckSeverity, number> = { ok: 0, info: 1, warn: 2, alert: 3 };
  return check.checks
    .filter((c) => c.available)
    .reduce<CheckSeverity>((acc, c) => (rank[c.severity] > rank[acc] ? c.severity : acc), "ok");
}

const SEVERITY_ICON: Record<CheckSeverity, string> = { ok: "🟢", info: "⚪", warn: "🟡", alert: "🔴" };

export function buildDailyDigest(positionChecks: PositionCheck[], urgencies: Map<string, UrgencyResult>): string {
  if (positionChecks.length === 0) return "WATCH daily digest — no open positions to report on.";

  const lines = [`WATCH daily digest — ${positionChecks.length} position(s) checked.`, ""];
  for (const pc of positionChecks) {
    const worst = worstSeverity(pc);
    const urgency = urgencies.get(pc.symbol);
    const tripped = pc.checks.filter((c) => c.available && c.severity !== "ok" && c.severity !== "info");
    lines.push(`${SEVERITY_ICON[worst]} ${pc.symbol} — ${urgency ? urgency.band : "urgency n/a"}`);
    if (tripped.length === 0) {
      lines.push("   No checks flagged.");
    } else {
      for (const c of tripped) lines.push(`   • [${c.severity}] ${c.label}: ${c.detail}`);
    }
    const unavailable = pc.checks.filter((c) => !c.available).length;
    if (unavailable > 0) lines.push(`   (${unavailable} check(s) unavailable — see position page for reasons; silence there means "no data", not "checked and fine.")`);
  }
  return lines.join("\n");
}

export function buildWeeklyDigest(positionChecks: PositionCheck[], scoreHistory: ScoreHistoryEntry[]): string {
  const lines = [`WATCH weekly digest — ${positionChecks.length} position(s).`, ""];

  lines.push("Score the scorer — predicted range vs. realised move:");
  const reconciled = scoreHistory.filter((e) => e.realisedPriceUsd != null);
  if (reconciled.length === 0) {
    lines.push("  No reconciled predictions yet this week (see urgency.ts's recordRealisedOutcome — needs real persistence before this is meaningful in production).");
  } else {
    for (const e of reconciled) {
      lines.push(
        `  ${e.symbol}: predicted [${e.expectedRangeLow.toFixed(2)}, ${e.expectedRangeHigh.toFixed(2)}], realised ${e.realisedPriceUsd?.toFixed(2)} — ${e.withinPredictedRange ? "within range" : "OUTSIDE range"}.`,
      );
    }
  }

  lines.push("");
  lines.push("Per-position summary:");
  for (const pc of positionChecks) {
    const worst = worstSeverity(pc);
    lines.push(`  ${SEVERITY_ICON[worst]} ${pc.symbol} — worst severity this week: ${worst}`);
  }
  return lines.join("\n");
}
