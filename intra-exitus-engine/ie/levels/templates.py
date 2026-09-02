"""Regime-conditional level templates.

Turns a regime call + the OU fit + a few price features into a concrete plan:
entry zone, stop, targets, a time-stop, an expected reward (R multiples), and a
confidence. Three templates, one per regime:

  mean-revert  -> fade a stretch back to the OU mean. Entry when price is stretched
                  >= enter_sigma from the OU mean; stop beyond stop_sigma; target the
                  mean. Time-stop = N half-lives. Bias is set by WHICH side price is
                  stretched — never by the ML.
  trend        -> buy pullbacks in an uptrend / sell rallies in a downtrend. Entry
                  near a moving-average anchor; stop beyond recent structure minus an
                  ATR buffer (the dynamic buffer); targets at R multiples. Bias from
                  the actual trend sign.
  high-vol     -> ABSTAIN. Return a plan with confidence "insufficient" and no levels.

Everything is expressed so the geometry is self-consistent: for a long,
stop < entry < targets; for a short, targets < entry < stop. `expected_r` is the
reward-to-risk ratio implied by the levels. Direction always comes from the
geometry here, honouring the finding that the classifier can't call direction.

REVIEW FIXES (2026-08):
  * #1 Mean-revert now ABSTAINS when |z| >= stop_sigma — a stretch already beyond
    the stop distance has no room to fade and previously shipped inverted geometry
    (stop inside the entry zone, negative risk).
  * #2/#6 Unified `expected_r = reward-to-FIRST-target / initial risk` across BOTH
    templates, and set enter_sigma = stop_sigma/2 so the entry threshold coincides
    with the ~1R boundary instead of being permanently sub-1R. The mean-revert
    primary target is the mean (the intermediate partial was dropped for v1).
  * #8 Trend template guards the incoherent case (a "long" printing fresh 20-day
    lows / a "short" printing fresh highs) — direction and structure disagree.

REVIEW FIXES (round 2, 2026-08):
  * #1/#6 `expected_r` is no longer a geometric constant/ratio. It is now the
    trade's EXPECTED R (expectancy = p*R - (1-p)), where p = P(target before stop)
    from a first-passage barrier model (see barrier.py) driven by an estimated
    drift and volatility. Mean-revert derives drift/vol from the OU fit; trend
    takes them as inputs from the pipeline. If p can't be estimated, the plan
    downgrades to "watch" rather than inventing an edge. "Actionable" now means
    positive expectancy (>= min_expectancy), not reward:risk >= 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .barrier import expectancy
from .ou import OUParams


@dataclass(frozen=True)
class LevelConfig:
    # mean-revert. enter_sigma defaults to stop_sigma/2 so the entry trigger sits
    # at the ~1R boundary (fix #2): shallower stretches can never clear min_expected_r.
    enter_sigma: float = 1.5     # need >= this many sigma of stretch to act
    stop_sigma: float = 3.0      # stop beyond this many sigma from the mean; |z|>=this abstains (fix #1)
    time_stop_half_lives: float = 2.0  # exit if not reverted in ~this many half-lives
    max_half_life: float = 40.0  # half-life beyond this => not actionable (abstain)
    # trend
    atr_buffer: float = 1.5      # stop = structure -/+ this many ATRs (dynamic buffer)
    pullback_atr: float = 0.5    # entry zone half-width around the anchor, in ATRs
    trend_targets_r: tuple[float, ...] = (2.0, 4.0, 6.0)  # R multiples
    max_stop_frac: float = 0.15  # stop farther than this (fraction of price) => too loose to be actionable
    # shared. expected_r is now EXPECTED R (expectancy = p*R - (1-p)), not a
    # reward:risk ratio, so the actionable bar is "positive edge" (fix #1/#6).
    min_expectancy: float = 0.0  # expected R at/below this => downgrade to "watch"


@dataclass(frozen=True)
class TradePlan:
    """Engine-side plan. Mirrors the website's EntryExitPlan contract, plus the
    reframe fields (regime / expected_r / confidence)."""

    ticker: str
    regime: str                       # "trend" | "mean-revert" | "high-vol"
    bias: str                         # "long" | "short" | "none"
    confidence: str                   # "actionable" | "watch" | "insufficient"
    entry_zone: tuple[float, float] | None
    stop: float | None
    targets: list[float]
    expected_r: float | None
    time_stop: str
    rationale: str
    invalidations: list[str] = field(default_factory=list)
    sizing_pct: float | None = None  # % of book; set by the sizing layer

    def with_sizing(self, sizing_pct: float | None) -> "TradePlan":
        from dataclasses import replace
        return replace(self, sizing_pct=sizing_pct)

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "regime": self.regime,
            "bias": self.bias,
            "confidence": self.confidence,
            "entryZone": list(self.entry_zone) if self.entry_zone else None,
            "stop": self.stop,
            "targets": self.targets,
            "expectedR": self.expected_r,
            "sizingPct": self.sizing_pct,
            "timeStop": self.time_stop,
            "rationale": self.rationale,
            "invalidations": self.invalidations,
        }


def _round(x: float, nd: int = 2) -> float:
    return float(round(x, nd))


def abstain_plan(ticker: str, why: str) -> TradePlan:
    return TradePlan(
        ticker=ticker,
        regime="high-vol",
        bias="none",
        confidence="insufficient",
        entry_zone=None,
        stop=None,
        targets=[],
        expected_r=None,
        time_stop="—",
        rationale=why,
        invalidations=[],
    )


def mean_revert_plan(
    ticker: str,
    price: float,
    ou: OUParams,
    cfg: LevelConfig | None = None,
) -> TradePlan:
    """Fade a stretch back to the OU mean. `ou` is fit on LOG price; `price` is the
    latest raw close. Bias is decided by which side of the mean price sits."""
    cfg = cfg or LevelConfig()
    if not ou.reverts or not np.isfinite(ou.half_life):
        return abstain_plan(ticker, "No mean reversion in the window (OU non-reverting).")
    if ou.half_life > cfg.max_half_life:
        return TradePlan(
            ticker=ticker, regime="mean-revert", bias="none", confidence="insufficient",
            entry_zone=None, stop=None, targets=[], expected_r=None, time_stop="—",
            rationale=f"Half-life {ou.half_life:.0f}d exceeds the {cfg.max_half_life:.0f}d "
                      f"actionable limit — reversion too slow to trade.",
            invalidations=[],
        )

    log_p = np.log(price)
    z = (log_p - ou.mu) / ou.sigma_eq  # standardized stretch (in sigma)
    mean_price = float(np.exp(ou.mu))

    if abs(z) < cfg.enter_sigma:
        return TradePlan(
            ticker=ticker, regime="mean-revert", bias="none", confidence="watch",
            entry_zone=None, stop=None, targets=[], expected_r=None, time_stop="—",
            rationale=f"Only {abs(z):.1f} sigma from the mean — inside the "
                      f"{cfg.enter_sigma:.1f} sigma entry threshold. Wait for a wider stretch.",
            invalidations=[f"Re-check when price stretches past {cfg.enter_sigma:.1f} sigma."],
        )

    # Fix #1: a stretch already at/beyond the stop distance has no room to fade —
    # entering here would put the stop inside the entry zone (negative risk).
    if abs(z) >= cfg.stop_sigma:
        return abstain_plan(
            ticker, f"Price is {abs(z):.1f} sigma out — already beyond the "
            f"{cfg.stop_sigma:.0f} sigma stop distance, no room to fade.",
        )

    # Target the mean (the reversion thesis). expected_r is measured to this first
    # target, the same convention the trend template uses (fix #2/#6).
    if z > 0:  # stretched HIGH -> fade short
        bias = "short"
        entry_hi = float(np.exp(ou.mu + abs(z) * ou.sigma_eq))       # ~ current
        entry_lo = float(np.exp(ou.mu + cfg.enter_sigma * ou.sigma_eq))
        entry_zone = (min(entry_lo, entry_hi), max(entry_lo, entry_hi))
        stop = float(np.exp(ou.mu + cfg.stop_sigma * ou.sigma_eq))
        entry_ref = entry_zone[1]
    else:  # stretched LOW -> fade long
        bias = "long"
        entry_lo = float(np.exp(ou.mu - abs(z) * ou.sigma_eq))       # ~ current
        entry_hi = float(np.exp(ou.mu - cfg.enter_sigma * ou.sigma_eq))
        entry_zone = (min(entry_lo, entry_hi), max(entry_lo, entry_hi))
        stop = float(np.exp(ou.mu - cfg.stop_sigma * ou.sigma_eq))
        entry_ref = entry_zone[0]

    targets = [_round(mean_price)]

    # Expectancy from the OU first-passage, in LOG space (OU is fit on log price).
    # The pull toward the mean IS the drift toward the target: theta * distance.
    entry_log = float(np.log(entry_ref))
    a = abs(ou.mu - entry_log)                 # entry -> target (the mean)
    b = abs(entry_log - float(np.log(stop)))   # entry -> stop
    drift_toward_target = ou.theta * a
    expected_r = expectancy(a, b, drift_toward_target, ou.sigma_resid)
    time_days = cfg.time_stop_half_lives * ou.half_life
    confidence = (
        "actionable" if (expected_r is not None and expected_r >= cfg.min_expectancy)
        else "watch"
    )
    return TradePlan(
        ticker=ticker,
        regime="mean-revert",
        bias=bias,
        confidence=confidence,
        entry_zone=(_round(entry_zone[0]), _round(entry_zone[1])),
        stop=_round(stop),
        targets=targets,
        expected_r=None if expected_r is None else _round(expected_r, 2),
        time_stop=f"Exit if not reverted toward the mean within ~{time_days:.0f} "
                  f"trading days ({cfg.time_stop_half_lives:.0f}x half-life).",
        rationale=f"Price is {abs(z):.1f} sigma {'above' if z > 0 else 'below'} its "
                  f"{ou.half_life:.0f}-day OU mean of {mean_price:.2f}; fade back toward it. "
                  f"Stop beyond {cfg.stop_sigma:.0f} sigma so you're wrong on the process, "
                  f"not on noise.",
        invalidations=[
            f"A close beyond {_round(stop)} voids the reversion thesis.",
            "Regime flips to trend or high-vol on the next read — stand aside.",
        ],
    )


def trend_plan(
    ticker: str,
    price: float,
    anchor: float,
    atr: float,
    swing_low: float,
    swing_high: float,
    direction: str,
    drift_per_bar: float = float("nan"),
    vol_per_bar: float = float("nan"),
    cfg: LevelConfig | None = None,
) -> TradePlan:
    """Buy pullbacks (long) / sell rallies (short) around a moving-average `anchor`,
    with an ATR-buffered stop beyond recent structure and R-multiple targets.

    `drift_per_bar` / `vol_per_bar` are the per-bar drift (signed TOWARD the trade
    direction) and volatility in PRICE units; they drive the first-passage
    expectancy (fix #1). If they're not supplied (NaN), expected_r can't be
    estimated and the plan is downgraded to "watch".

    Fix #8: `direction` (a slow-MA read) and the swing structure (a short window)
    can disagree. If a "long" is printing fresh swing lows (or a "short" fresh
    highs), the trend call and the structure contradict each other — abstain
    rather than fade the wrong way into a broken stop."""
    cfg = cfg or LevelConfig()
    if atr <= 0:
        return abstain_plan(ticker, "No usable ATR — cannot size a trend stop.")

    tol = 0.5 * atr
    if direction == "up" and price <= swing_low + tol:
        return abstain_plan(
            ticker, "Incoherent: 'uptrend' but price is at fresh swing lows — "
            "direction and structure disagree.")
    if direction == "down" and price >= swing_high - tol:
        return abstain_plan(
            ticker, "Incoherent: 'downtrend' but price is at fresh swing highs — "
            "direction and structure disagree.")

    if direction == "up":
        bias = "long"
        entry_zone = (_round(anchor - cfg.pullback_atr * atr),
                      _round(anchor + cfg.pullback_atr * atr))
        entry_ref = entry_zone[1]
        stop = _round(swing_low - cfg.atr_buffer * atr)
        risk = entry_ref - stop
        # Targets are R multiples; drop any that fall to/below zero (nonsensical).
        targets = [_round(entry_ref + r * risk) for r in cfg.trend_targets_r]
        targets = [t for t in targets if t > 0]
    else:
        bias = "short"
        entry_zone = (_round(anchor - cfg.pullback_atr * atr),
                      _round(anchor + cfg.pullback_atr * atr))
        entry_ref = entry_zone[0]
        stop = _round(swing_high + cfg.atr_buffer * atr)
        risk = stop - entry_ref
        targets = [_round(entry_ref - r * risk) for r in cfg.trend_targets_r]
        targets = [t for t in targets if t > 0]  # a short can't target a negative price

    if risk <= 0 or not targets:
        return abstain_plan(ticker, "Structure and entry overlap — no clean stop.")

    # A stop farther than max_stop_frac of price makes the R-targets fantasy over a
    # swing horizon — keep the levels but downgrade to "watch" and say why.
    stop_frac = risk / entry_ref
    too_loose = stop_frac > cfg.max_stop_frac
    loose_note = (
        f" NOTE: stop is {stop_frac:.0%} of price (>{cfg.max_stop_frac:.0%}) — "
        f"structure is too loose for a clean swing; watch, don't force it."
        if too_loose else ""
    )

    # Fix #1: expected_r is the first-passage EXPECTANCY to the first target, not a
    # constant. Drift toward the target + vol set P(target before stop).
    a = abs(targets[0] - entry_ref)   # entry -> first target
    b = risk                          # entry -> stop
    expected_r = expectancy(a, b, drift_per_bar, vol_per_bar)

    if expected_r is None:
        confidence = "watch"
        edge_note = " Edge (drift/vol) could not be estimated — watch, don't act."
    elif too_loose or expected_r < cfg.min_expectancy:
        confidence = "watch"
        edge_note = "" if too_loose else f" Expectancy {expected_r:+.2f}R <= bar — watch."
    else:
        confidence = "actionable"
        edge_note = ""
    return TradePlan(
        ticker=ticker,
        regime="trend",
        bias=bias,
        confidence=confidence,
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        expected_r=None if expected_r is None else _round(expected_r, 2),
        time_stop="Re-evaluate at the next earnings print, or if the first target "
                  "isn't tagged within ~6 weeks.",
        rationale=f"{'Up' if direction == 'up' else 'Down'}trend; enter on a pullback to "
                  f"the {anchor:.2f} anchor with the stop {cfg.atr_buffer:.1f} ATR beyond "
                  f"the recent {'swing low' if direction == 'up' else 'swing high'} "
                  f"(dynamic buffer). Targets scale at {'/'.join(f'{r:.0f}R' for r in cfg.trend_targets_r)}."
                  + loose_note + edge_note,
        invalidations=[
            f"A close beyond {stop} breaks structure and voids the trend setup.",
            "Regime flips to high-vol — halve size or stand aside.",
        ],
    )
