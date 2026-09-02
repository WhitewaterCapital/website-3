"""Orchestration: prices -> features -> regime -> template -> sizing -> plan.

`plan_for_ticker` is the whole model in one call, evaluated **as of the latest
bar** (strictly point-in-time). It:

  1. computes the PIT feature frame and takes the latest row,
  2. asks the trained regime classifier for class probabilities,
  3. gates on high-vol (abstain if the model is confident it's dangerous),
  4. dispatches to the matching level template (OU band for mean-revert, ATR
     pullback for trend) — direction from the geometry, never the ML,
  5. sizes the position (risk budget + vol target, net of costs) and downgrades
     to "watch" if costs eat the edge.

The classifier must already be fit (see regime/classifier.py). Nothing here looks
into the future: features are as-of, and the plan is for the next session.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features.price import FeatureConfig, compute_features
from .levels.ou import fit_ou
from .levels.templates import (
    LevelConfig,
    TradePlan,
    abstain_plan,
    mean_revert_plan,
    trend_plan,
)
from .regime.classifier import RegimeModel
from .sizing.size import SizeConfig, compute_size


@dataclass(frozen=True)
class PipelineConfig:
    ou_window: int = 120         # trailing bars for the OU fit (log-price)
    swing_window: int = 20       # bars for swing high/low structure
    abstain_prob: float = 0.50   # P(high-vol) at/above this => abstain
    feature: FeatureConfig = FeatureConfig()
    level: LevelConfig = LevelConfig()
    size: SizeConfig = SizeConfig()


def plan_for_ticker(
    ticker: str,
    prices: pd.DataFrame,
    model: RegimeModel,
    feature_cols: list[str],
    cfg: PipelineConfig | None = None,
) -> TradePlan:
    cfg = cfg or PipelineConfig()
    feats = compute_features(prices, cfg.feature)
    latest = feats.iloc[[-1]]
    # Fix #5: require the SAME warm-up the training set used (mom_252 present).
    # A row before full warm-up has too little history to classify or to fit OU
    # (which raises on <20 finite points) — abstain rather than run on it.
    if "mom_252" not in feats.columns or not np.isfinite(feats["mom_252"].iloc[-1]):
        return abstain_plan(ticker, "Not enough history for a plan (warming up).")

    proba = model.predict_proba(latest[feature_cols]).iloc[0]
    p_highvol = float(proba.get("high-vol", 0.0))
    if p_highvol >= cfg.abstain_prob:
        return abstain_plan(
            ticker, f"High-vol regime (p={p_highvol:.0%}) — standing aside."
        )

    # Pick between the tradeable regimes.
    tradeable = {k: float(proba.get(k, 0.0)) for k in ("trend", "mean-revert")}
    regime = max(tradeable, key=tradeable.get)

    price = float(prices["close"].iloc[-1])
    row = feats.iloc[-1]

    if regime == "mean-revert":
        log_p = np.log(prices["close"].to_numpy())[-cfg.ou_window:]
        ou = fit_ou(log_p, dt=1.0)
        plan = mean_revert_plan(ticker, price, ou, cfg.level)
        entry_ref = None if plan.entry_zone is None else (
            plan.entry_zone[1] if plan.bias == "short" else plan.entry_zone[0]
        )
    else:  # trend
        atr = float(row["atr_14"])
        # Fix #4: compute EMA-21 directly from the price series rather than
        # reconstructing it as price/(1+dist_ema_21) — the reconstruction would
        # silently drift if the feature definition ever changed.
        anchor = float(prices["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        swing_low = float(prices["low"].rolling(cfg.swing_window).min().iloc[-1])
        swing_high = float(prices["high"].rolling(cfg.swing_window).max().iloc[-1])
        direction = "up" if float(row["dist_sma_50"]) >= 0 else "down"
        # Per-bar drift (signed toward the trade) and vol, in PRICE units, for the
        # first-passage expectancy (fix #1). Drift from recent momentum; vol from
        # daily realised vol. Weak/adverse trends -> near-zero or negative edge.
        per_bar_ret = float(row["mom_63"]) / 63.0
        drift_per_bar = (per_bar_ret if direction == "up" else -per_bar_ret) * price
        rv = float(row["rv_21"]) if np.isfinite(row["rv_21"]) else float(row["ewma_vol"])
        vol_per_bar = (rv / np.sqrt(cfg.feature.trading_days)) * price
        plan = trend_plan(ticker, price, anchor, atr, swing_low, swing_high,
                          direction, drift_per_bar, vol_per_bar, cfg=cfg.level)
        entry_ref = None if plan.entry_zone is None else (
            plan.entry_zone[1] if plan.bias == "long" else plan.entry_zone[0]
        )

    # Size it (only when we have a real entry/stop).
    if plan.entry_zone is None or plan.stop is None or entry_ref is None:
        return plan
    asset_vol = float(row["rv_21"]) if np.isfinite(row["rv_21"]) else float(row["ewma_vol"])
    sized = compute_size(entry_ref, plan.stop, asset_vol, plan.expected_r, cfg.size)
    plan = plan.with_sizing(sized.sizing_pct)
    if not sized.tradeable and plan.confidence == "actionable":
        from dataclasses import replace
        plan = replace(
            plan, confidence="watch",
            rationale=plan.rationale + f" (Net of costs the edge is {sized.net_r}R — "
            f"below the {cfg.size.min_net_r}R bar; watch, don't chase.)",
        )
    return plan
