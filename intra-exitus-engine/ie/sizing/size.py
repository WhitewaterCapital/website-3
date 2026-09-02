"""Position sizing.

Two independent caps, take the smaller, then clip to a hard maximum:

  * Risk budget — size so that being stopped out costs at most `risk_budget_pct`
    of the book. If the stop is `s` away from entry as a fraction of price, the
    weight that risks exactly the budget is  risk_budget_pct / s.
  * Volatility target — size so the position's own volatility contributes about
    `target_vol` (annualised) to the book:  target_vol / asset_vol.

Then a **cost haircut**: a round-trip cost of `cost_bps` is converted into R units
(cost as a multiple of the trade's risk) and subtracted from the expected reward.
If the net reward:risk falls below `min_net_r`, the caller should downgrade the
plan to "watch" — a trade whose edge is eaten by costs isn't a trade.

Fractional Kelly is deliberately NOT applied yet: Kelly needs an empirical win
rate and payoff, which only the walk-forward backtest (Task #5) can supply
honestly. Sizing off a fabricated win probability is how people blow up. Once the
backtest yields per-regime hit rates, a half-Kelly cap slots in here.

FIX #7 (2026-08): a non-finite or non-positive `asset_vol` no longer falls through
to max_weight (which lifted the cap exactly when vol was unknown). Unknown vol =>
the vol cap is zero => the position is untradeable, not maximal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SizeConfig:
    risk_budget_pct: float = 0.01   # lose at most 1% of book at the stop
    target_vol: float = 0.10        # per-position annualised vol contribution
    max_weight: float = 0.20        # hard cap on any single position
    cost_bps: float = 10.0          # round-trip transaction cost, basis points
    # expected_r is now EXPECTANCY (expected R = p*R-(1-p)); a trade is only
    # tradeable if its expectancy net of costs stays positive.
    min_net_r: float = 0.0          # net expectancy (R) below this => not tradeable


@dataclass(frozen=True)
class SizeResult:
    sizing_pct: float          # % of book (0..max_weight*100)
    gross_r: float | None      # reward:risk before costs
    net_r: float | None        # reward:risk after the cost haircut
    binding: str               # which cap bound: "risk" | "vol" | "max"
    tradeable: bool            # net_r >= min_net_r


def compute_size(
    entry: float,
    stop: float,
    asset_vol: float,
    expected_r: float | None,
    cfg: SizeConfig | None = None,
) -> SizeResult:
    """Size a single position and haircut its expected reward for costs.

    `asset_vol` is the annualised realised vol of the name (e.g. rv_21)."""
    cfg = cfg or SizeConfig()
    stop_frac = abs(entry - stop) / entry if entry > 0 else 0.0
    if stop_frac <= 0:
        return SizeResult(0.0, expected_r, expected_r, "risk", False)

    risk_cap = cfg.risk_budget_pct / stop_frac
    # Unknown vol (NaN/inf/<=0) => cannot vol-target => cap at zero, never max_weight.
    vol_cap = cfg.target_vol / asset_vol if (np.isfinite(asset_vol) and asset_vol > 0) else 0.0

    weight = min(risk_cap, vol_cap, cfg.max_weight)
    binding = (
        "risk" if weight == risk_cap
        else "vol" if weight == vol_cap
        else "max"
    )

    # Cost in R units: round-trip cost as a fraction of price, divided by the
    # per-unit risk (also a fraction of price).
    cost_r = (cfg.cost_bps / 1e4) / stop_frac
    net_r = None if expected_r is None else float(expected_r - cost_r)
    tradeable = net_r is not None and net_r >= cfg.min_net_r and weight > 0

    return SizeResult(
        sizing_pct=round(weight * 100.0, 2),
        gross_r=expected_r,
        net_r=None if net_r is None else round(net_r, 2),
        binding=binding,
        tradeable=tradeable,
    )
