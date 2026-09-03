"""CHAOS-03 — cost-aware execution assumptions.

The central honesty rule: every simulated fill happens at the FAR SIDE of the
spread plus modelled impact. Never mid-price. A model that trades dislocations
is, by construction, trying to trade exactly when spreads are widest — pricing
fills at mid would hide the one cost that matters most to this strategy.

On top of that:
  * a minimum holding period prevents the backtest from "trading" faster than
    any realistic execution/latency budget would allow,
  * a maximum turnover-per-session cap bounds how much churn is allowed even
    if the signal wants more (breaches are reported, not silently dropped),
  * every result is reported gross AND net, side by side, at every stage,
  * a cost-sensitivity table (1x/2x/3x the modelled cost) is a first-class
    output, not an afterthought — see `cost_sensitivity_table`.

This is not high-frequency trading and nothing here assumes HFT-grade
execution: no colocated fills, no queue-position modelling, no sub-second
latency assumptions. The holding-period floor and the far-side-of-spread fill
assumption exist precisely because the honest execution horizon here is
intraday (1-15 minutes), not microseconds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import ExecutionConfig


def fill_price(
    mid: float,
    spread: float,
    side: str,
    chaos_state: str,
    cfg: ExecutionConfig | None = None,
    participation: float = 0.0,
) -> float:
    """Assumed fill price for a trade of the given `side` ('buy' or 'sell'),
    given the current mid price, the BASE (calm-state) full spread, and the
    prevailing chaos state.

    fill = mid +/- (state-widened spread / 2) +/- linear impact

    The spread is widened by `cfg.state_spread_multiplier[chaos_state]` before
    being applied — "spreads are widest exactly when this model wants to
    trade" is encoded directly into the fill assumption, not left to a
    backtest footnote. `participation` (fraction of expected bar volume this
    order represents, in [0, 1]) drives a simple linear impact term; 0.0
    (the default) means "impact not modelled for this call", which is honest
    for a small book but must be raised for anything sized to matter.

    Buys fill ABOVE mid (far side = ask side); sells fill BELOW mid (far side
    = bid side). Mid-price fills are never returned by this function."""
    cfg = cfg or ExecutionConfig()
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if chaos_state not in cfg.state_spread_multiplier:
        raise ValueError(
            f"unknown chaos_state {chaos_state!r}; expected one of "
            f"{sorted(cfg.state_spread_multiplier)}"
        )
    mult = cfg.state_spread_multiplier[chaos_state]
    effective_spread = max(spread, 0.0) * mult
    half = effective_spread / 2.0
    impact = max(participation, 0.0) * cfg.impact_bps_per_unit_participation / 1e4 * mid
    if side == "buy":
        return mid + half + impact
    return mid - half - impact


@dataclass
class ExecutionReport:
    """Gross vs. net, side by side, plus the execution-constraint bookkeeping
    the doc asks to be reported (min holding period, turnover cap)."""

    gross_returns: list = field(default_factory=list)
    net_returns: list = field(default_factory=list)
    gross_total: float = 0.0
    net_total: float = 0.0
    total_cost: float = 0.0
    n_trades: int = 0
    turnover: float = 0.0
    min_holding_bars: int = 0
    max_turnover_per_session: float = float("inf")
    turnover_cap_breached: bool = False  # True if the signal ever wanted more
                                          # turnover than the session cap allowed

    @property
    def net_positive(self) -> bool:
        return self.net_total > 0.0

    def summary(self) -> dict:
        return {
            "gross_total": round(self.gross_total, 6),
            "net_total": round(self.net_total, 6),
            "net_positive": self.net_positive,
            "total_cost": round(self.total_cost, 6),
            "n_trades": self.n_trades,
            "turnover": round(self.turnover, 4),
            "turnover_cap_breached": self.turnover_cap_breached,
            "min_holding_bars": self.min_holding_bars,
            "max_turnover_per_session": self.max_turnover_per_session,
        }


def backtest_signal(
    mid_prices: pd.Series,
    signal: pd.Series,
    chaos_states: pd.Series,
    spread: pd.Series | float,
    cfg: ExecutionConfig | None = None,
    cost_multiplier: float = 1.0,
) -> ExecutionReport:
    """Bar-by-bar, cost-aware backtest of a single-name position signal.

    `signal` is the DESIRED position (e.g. in {-1, 0, +1}, but any real value
    is accepted) known as of each bar's close. To stay causal, the decision
    made using bar i-1's information is executed at bar i-1's price and earns
    the return from bar i-1 to bar i (never same-bar). `chaos_states` (labels
    from `chaos.state.run_state_machine`) drive the state-scaled spread via
    `fill_price`. `spread` is the BASE full spread (a constant or a per-bar
    Series) BEFORE the chaos-state multiplier and before `cost_multiplier`.

    Execution constraints:
      * `cfg.min_holding_bars` — once a position is opened or changed, no
        further change is allowed for that many bars.
      * `cfg.max_turnover_per_session` — cumulative |position change| within
        one calendar session (bars sharing the same normalised date; if the
        index is not a DatetimeIndex the whole series is one session) is
        capped; a desired change beyond the cap is skipped and
        `turnover_cap_breached` is set.

    `cost_multiplier` scales the realised trading cost (not the gross return)
    — this is the knob `cost_sensitivity_table` sweeps over 1x/2x/3x."""
    cfg = cfg or ExecutionConfig()
    idx = mid_prices.index
    n = len(idx)
    if n < 2:
        return ExecutionReport(
            min_holding_bars=cfg.min_holding_bars,
            max_turnover_per_session=cfg.max_turnover_per_session,
        )

    spread_s = spread if isinstance(spread, pd.Series) else pd.Series(float(spread), index=idx)

    if isinstance(idx, pd.DatetimeIndex):
        session_of = idx.normalize()
    else:
        session_of = pd.Index([0] * n)

    pos = 0.0
    last_change_bar = -(10 ** 9)
    session_turnover: dict = defaultdict(float)
    cap_breached = False

    gross_returns: list[float] = []
    net_returns: list[float] = []
    total_cost = 0.0
    total_turnover = 0.0
    n_trades = 0

    mid = mid_prices.to_numpy(dtype=float)
    sig = signal.reindex(idx).to_numpy(dtype=float)
    states = chaos_states.reindex(idx).to_numpy()
    spr = spread_s.to_numpy(dtype=float)

    for i in range(1, n):
        price_prev, price = mid[i - 1], mid[i]
        desired = sig[i - 1]
        sess = session_of[i - 1]

        can_change = (i - last_change_bar) >= cfg.min_holding_bars
        cost_this_bar = 0.0
        if desired != pos and can_change:
            turnover_amt = abs(desired - pos)
            if session_turnover[sess] + turnover_amt <= cfg.max_turnover_per_session:
                side = "buy" if desired > pos else "sell"
                fp = fill_price(price_prev, spr[i - 1], side, states[i - 1], cfg)
                cost_frac = abs(fp - price_prev) / price_prev if price_prev else 0.0
                cost_this_bar = cost_frac * turnover_amt * cost_multiplier
                pos = desired
                last_change_bar = i
                session_turnover[sess] += turnover_amt
                total_turnover += turnover_amt
                n_trades += 1
            else:
                cap_breached = True

        bar_gross_ret = ((price - price_prev) / price_prev if price_prev else 0.0) * pos
        gross_returns.append(bar_gross_ret)
        net_returns.append(bar_gross_ret - cost_this_bar)
        total_cost += cost_this_bar

    return ExecutionReport(
        gross_returns=gross_returns,
        net_returns=net_returns,
        gross_total=float(np.sum(gross_returns)),
        net_total=float(np.sum(net_returns)),
        total_cost=float(total_cost),
        n_trades=n_trades,
        turnover=float(total_turnover),
        min_holding_bars=cfg.min_holding_bars,
        max_turnover_per_session=cfg.max_turnover_per_session,
        turnover_cap_breached=cap_breached,
    )


def cost_sensitivity_table(
    mid_prices: pd.Series,
    signal: pd.Series,
    chaos_states: pd.Series,
    spread: pd.Series | float,
    cfg: ExecutionConfig | None = None,
    multipliers: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> pd.DataFrame:
    """The doc's actual "done when" bar: net performance at 1x/2x/3x the
    modelled cost, computed for real (not hardcoded) by re-running the same
    backtest with `cost_multiplier` swept. `net_positive` is read straight off
    each run's own P&L sign — this function makes no claim about whether the
    strategy survives 2x cost; it just measures and reports it, honestly,
    whichever way it comes out."""
    rows = []
    for m in multipliers:
        rep = backtest_signal(mid_prices, signal, chaos_states, spread, cfg, cost_multiplier=m)
        rows.append(
            {
                "cost_multiplier": m,
                "gross_total": rep.gross_total,
                "net_total": rep.net_total,
                "total_cost": rep.total_cost,
                "net_positive": rep.net_positive,
                "n_trades": rep.n_trades,
                "turnover_cap_breached": rep.turnover_cap_breached,
            }
        )
    return pd.DataFrame(rows)
