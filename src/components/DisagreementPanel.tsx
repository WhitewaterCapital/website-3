"use client";

import { useState } from "react";
import { Card, Badge } from "@/components/ui";
import {
  classifyDisagreement,
  HIGH_CONVICTION_CONFIDENCE_THRESHOLD,
  type DirectionalOutput,
} from "@/lib/models/disagreement";

// ═══════════════════════════════════════════════════════════════════════════
// IMP-16 — show the two kinds of disagreement SEPARATELY, never blended.
//
// Directional disagreement (models pointing opposite ways) and confidence
// disagreement (agreeing on direction, not on strength) get their own
// indicator each — see src/lib/models/disagreement.ts's classifyDisagreement
// for the definitions. A review banner fires only on the directional kind at
// high conviction, per the spec.
//
// DATA SOURCE: no existing export in this repo carries more than one model's
// independent directional call on the same target with a usable confidence —
// Aurora's nowcast factors are the closest natural fit, but every factor in
// the live export is `skillful: false` / `expected_return: null` /
// `confidence: "insufficient"` today (see public/data/aurora/latest.json),
// so reading them here would mean feeding the classifier confidence-0 noise,
// not a real disagreement read. Rather than fabricate live-looking numbers
// from a signal that isn't there, this panel uses two small, clearly-labeled
// SAMPLE DirectionalOutput sets built to demonstrate the classifier on a
// clean directional split and on a clean confidence split — see the caption
// below. Swap in a real DirectionalOutput[] the moment more than one model
// produces an independent, confident directional call on the same bucket.
// ═══════════════════════════════════════════════════════════════════════════

type ScenarioKey = "directional" | "confidence";

const SCENARIOS: Record<
  ScenarioKey,
  { label: string; blurb: string; outputs: DirectionalOutput[] }
> = {
  directional: {
    label: "Directional split",
    blurb: "Four models on the same bucket, confidently pointing opposite ways.",
    outputs: [
      { modelId: "Model A", direction: 72, confidence: 0.8 },
      { modelId: "Model B", direction: 58, confidence: 0.7 },
      { modelId: "Model C", direction: -65, confidence: 0.75 },
      { modelId: "Model D", direction: -50, confidence: 0.6 },
    ],
  },
  confidence: {
    label: "Confidence split",
    blurb: "Same four models, all bullish this time — but far apart on how strongly.",
    outputs: [
      { modelId: "Model A", direction: 80, confidence: 0.9 },
      { modelId: "Model B", direction: 25, confidence: 0.5 },
      { modelId: "Model C", direction: 55, confidence: 0.7 },
      { modelId: "Model D", direction: 10, confidence: 0.4 },
    ],
  },
};

// A 0..100 magnitude meter — sibling to ScoreBar, but for a non-diverging
// (always-positive) read. Same non-color-only discipline: role="img" +
// aria-label carry the number in words, and the fill grows from a fixed left
// edge so magnitude is legible as shape, not just as a color.
function MagnitudeBar({ value, tone }: { value: number; tone: "amber" | "rose" }) {
  const clamped = Math.max(0, Math.min(100, value));
  const barColor = tone === "amber" ? "bg-amber-500" : "bg-rose-500";
  return (
    <div
      className="relative h-2 w-full rounded-full bg-foreground/10"
      role="img"
      aria-label={`${clamped.toFixed(0)} out of 100`}
    >
      <div className={`absolute left-0 top-0 h-full rounded-full ${barColor}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

export function DisagreementPanel() {
  const [scenario, setScenario] = useState<ScenarioKey>("directional");
  const active = SCENARIOS[scenario];
  const result = classifyDisagreement(active.outputs);

  return (
    <Card title="Model disagreement — IMP-16">
      <div className="border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
        ⚠ <strong>SAMPLE — demonstrates the classifier.</strong> No export in this
        repo currently carries more than one model&apos;s confident, independent
        directional call on the same bucket (Aurora&apos;s nowcast factors are the
        closest fit, but every factor is reported not-skillful today). The
        DirectionalOutput entries below are constructed, not read from a live
        model — run through the real{" "}
        <code>classifyDisagreement()</code> in{" "}
        <code>src/lib/models/disagreement.ts</code>, not fabricated statistics.
      </div>

      <p className="mt-3 text-xs text-muted">
        Directional disagreement (models pointing opposite ways) and confidence
        disagreement (agreeing on direction, not on strength) are two different
        problems. Averaging them into one scalar hides both — shown separately
        below.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {(Object.keys(SCENARIOS) as ScenarioKey[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setScenario(key)}
            className={`border px-3 py-1.5 text-xs font-medium uppercase tracking-wide transition ${
              scenario === key
                ? "border-foreground bg-foreground text-background"
                : "border-hairline text-muted hover:text-foreground"
            }`}
          >
            {SCENARIOS[key].label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">{active.blurb}</p>

      {/* The four sample model reads themselves, so the numbers below are traceable. */}
      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
        {active.outputs.map((o) => (
          <div key={o.modelId} className="border-t border-hairline pt-1.5">
            <div className="font-medium text-foreground">{o.modelId}</div>
            <div className="tabular-nums text-muted">
              dir {o.direction > 0 ? "+" : ""}
              {o.direction} · conf {(o.confidence * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        <div>
          <div className="flex items-center justify-between">
            <span className="eyebrow">Directional disagreement</span>
            <Badge tone={result.directionalDisagreement ? "warn" : "neutral"}>
              {result.directionalDisagreement ? "Split" : "Aligned"}
            </Badge>
          </div>
          <p className="mt-2 text-xs text-foreground/80">
            Confidence-weighted:{" "}
            <span className="tabular-nums">{(result.directionalDetail.positiveWeightShare * 100).toFixed(0)}%</span>{" "}
            pointing up,{" "}
            <span className="tabular-nums">{(result.directionalDetail.negativeWeightShare * 100).toFixed(0)}%</span>{" "}
            pointing down.
          </p>
          <p className="mt-1 text-[11px] text-muted">
            Flags true when both sides carry at least 20% of total confidence weight — a lone low-confidence dissenter doesn&apos;t count.
          </p>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <span className="eyebrow">Confidence disagreement</span>
            <span className="tabular-nums text-sm font-semibold text-foreground">{result.confidenceDisagreement}</span>
          </div>
          <div className="mt-2">
            <MagnitudeBar value={result.confidenceDisagreement} tone="amber" />
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Spread in call strength (0–100) among models that agree on direction. Independent of the directional read above — never averaged into it.
          </p>
        </div>
      </div>

      <div className="mt-6 border-t border-hairline pt-4">
        <p className="text-xs text-foreground/80">
          Mean confidence (conviction):{" "}
          <span className="tabular-nums font-medium">{(result.meanConfidence * 100).toFixed(0)}%</span>{" "}
          <span className="text-muted">
            (review trigger fires above {(HIGH_CONVICTION_CONFIDENCE_THRESHOLD * 100).toFixed(0)}%)
          </span>
        </p>
      </div>

      {result.reviewFlag ? (
        <div className="mt-4 border border-rose-500/50 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-400">
          🚩 <strong>Human review triggered.</strong> High-conviction directional
          disagreement — models are confidently split on direction, not merely on
          strength.
        </div>
      ) : (
        <div className="mt-4 border border-hairline px-3 py-2 text-xs text-muted">
          No review trigger. {result.directionalDisagreement
            ? "Directional split present, but conviction is below the high-conviction bar."
            : "No directional split — confidence disagreement alone never triggers review."}
        </div>
      )}
    </Card>
  );
}
