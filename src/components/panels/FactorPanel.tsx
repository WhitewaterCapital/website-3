"use client";

// WW-FACTOR — Fama-French factor-exposure panel.
//
// DESCRIPTIVE RISK CONTEXT ONLY — NOT A CONVICTION SLOT.
// A factor beta answers "what STYLE does this name's return pattern look
// like" (market-sensitive, small-cap-like, value-like, high-quality-like,
// conservative-investment-like, momentum-chasing-like) — it does not answer
// "should I buy or sell this". A market beta of 1.3 is not bullish or
// bearish on its own: it says this name amplifies whatever the market does,
// in EITHER direction. A negative momentum beta is not a sell signal: it is
// a description of a style tilt (currently unloved by recent winners), and
// plenty of genuinely good, undervalued names sit there. Forcing either
// into `src/lib/models/conviction.ts`'s signed -100..100 directional slot
// score would misrepresent what the number means, so this panel's numbers
// are NEVER passed to `computeConviction` — see conviction.ts's own module
// comment on reserved/considered slots, which does not list this model, and
// see this file's own render path below, which never imports conviction.ts
// at all.

import { Card, Badge } from "@/components/ui";
import type { FactorExposure, FactorName } from "@/lib/models/factor-export";

const CONFIDENCE_LABEL: Record<FactorExposure["confidence"], string> = {
  ok: "Fitted",
  insufficient_history: "Not enough history",
  degenerate: "Regression degenerate",
};

const CONFIDENCE_TONE: Record<FactorExposure["confidence"], "up" | "warn" | "down"> = {
  ok: "up",
  insufficient_history: "warn",
  degenerate: "down",
};

// One-sentence, non-quant explanation of a single factor's fitted beta.
// `significant` (the engine's own t-stat >= ~1.96 flag) is appended as a
// caveat, never used to suppress the sentence — an insignificant beta is
// still honest information ("no measurable tilt detected here").
function explainBeta(factor: FactorName, beta: number, significant: boolean): string {
  const caveat = significant ? "" : " — not statistically distinguishable from zero over this window";
  const b = beta.toFixed(2);
  switch (factor) {
    case "Mkt-RF": {
      if (Math.abs(beta - 1) < 0.05) {
        return `Market beta ${b} — moves roughly in line with the overall market${caveat}.`;
      }
      const pct = Math.round(Math.abs(beta - 1) * 100);
      const dir = beta > 1 ? "more" : "less";
      return `Market beta ${b} — this stock swings about ${pct}% ${dir} than the market on average${caveat}.`;
    }
    case "SMB":
      return beta >= 0
        ? `Positive size tilt (SMB ${b}) — behaves more like a small-cap stock than a large-cap one${caveat}.`
        : `Negative size tilt (SMB ${b}) — behaves more like a large-cap stock than a small-cap one${caveat}.`;
    case "HML":
      return beta >= 0
        ? `Positive value tilt (HML ${b}) — behaves more like a cheap/value stock${caveat}.`
        : `Negative value tilt (HML ${b}) — behaves more like an expensive/growth stock${caveat}.`;
    case "RMW":
      return beta >= 0
        ? `Positive profitability tilt (RMW ${b}) — behaves more like a highly profitable company${caveat}.`
        : `Negative profitability tilt (RMW ${b}) — behaves more like a weaker-profitability company${caveat}.`;
    case "CMA":
      return beta >= 0
        ? `Positive investment tilt (CMA ${b}) — behaves more like a conservative, low-spending company${caveat}.`
        : `Negative investment tilt (CMA ${b}) — behaves more like an aggressively-investing/expanding company${caveat}.`;
    case "Mom":
      return beta >= 0
        ? `Positive momentum tilt (Mom ${b}) — currently rides stocks that have been trending up${caveat}.`
        : `Negative momentum tilt (Mom ${b}) — currently unloved by stocks that have been trending up${caveat}.`;
    default:
      return `${factor} beta ${b}${caveat}.`;
  }
}

export function FactorPanel({
  exposure,
  dataProvenance,
}: {
  exposure: FactorExposure;
  dataProvenance: "live" | "synthetic-demo";
}) {
  return (
    <Card
      title="Factor exposure (Fama-French)"
      action={<Badge tone={CONFIDENCE_TONE[exposure.confidence]}>{CONFIDENCE_LABEL[exposure.confidence]}</Badge>}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge tone={dataProvenance === "live" ? "up" : "warn"}>
          {dataProvenance === "live" ? "Live market data" : "Synthetic demo data"}
        </Badge>
        {dataProvenance !== "live" && (
          <span className="text-xs text-muted">
            This engine&apos;s current output on this sandbox — not a real market read.
          </span>
        )}
      </div>

      {exposure.confidence !== "ok" ? (
        <p className="text-sm text-foreground/80">
          {exposure.abstain_reason ?? "The engine abstained rather than show an unreliable beta."}
        </p>
      ) : (
        <>
          <ul className="space-y-2.5">
            {(exposure.betas ?? []).map((b) => (
              <li key={b.factor} className="text-sm text-foreground/80">
                — {explainBeta(b.factor, b.beta, b.significant)}
              </li>
            ))}
          </ul>

          <div className="mt-5 grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="eyebrow">R²</div>
              <div className="mt-1 text-sm font-semibold tabular-nums">
                {exposure.r2 != null ? exposure.r2.toFixed(2) : "—"}
              </div>
            </div>
            <div>
              <div className="eyebrow">Alpha (ann.)</div>
              <div className="mt-1 text-sm font-semibold tabular-nums">
                {exposure.alpha_annualized != null ? `${(exposure.alpha_annualized * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div>
              <div className="eyebrow">Days used</div>
              <div className="mt-1 text-sm font-semibold tabular-nums">{exposure.n_obs}</div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-muted">
            R² is how much of this window&apos;s daily return variation these six factors explain together — the
            rest is this name&apos;s own idiosyncratic behavior. Alpha is the leftover average return these factors
            do NOT explain, annualized; a small alpha over one window is not evidence of skill or mispricing on its
            own.
          </p>
        </>
      )}

      <p className="mt-4 text-[11px] text-muted">
        Descriptive risk context, not a directional call — this reading is intentionally not part of the Verdict
        card&apos;s composite conviction score above.
      </p>
    </Card>
  );
}
