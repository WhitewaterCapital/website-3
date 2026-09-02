"""Cross-sectional backtest engine.

Takes a long panel: one row per (date, security) with a `score` (known at that
date) and `fwd_ret` (the return realized over the following holding period). At
each rebalance it sorts into quantiles, forms a top(-minus-bottom) portfolio,
charges turnover costs, and records the per-date rank-IC. It reports a metrics
panel — NOT just cumulative return (dossier §11).

Assumptions the caller must honor for the result to be honest:
  - `score` uses only information public at `date` (point-in-time).
  - `fwd_ret` starts AFTER `date` (no same-bar fill).
  - the universe at each date includes then-listed names (survivorship).
The engine cannot enforce these — they are upstream data-integrity guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..validation.metrics import rank_ic, sharpe, max_drawdown


@dataclass
class BacktestResult:
    dates: list = field(default_factory=list)
    period_returns: list = field(default_factory=list)  # net of cost
    ic_series: list = field(default_factory=list)
    turnover_series: list = field(default_factory=list)
    mean_rank_ic: float = float("nan")
    ic_ir: float = float("nan")
    net_sharpe: float = float("nan")
    gross_sharpe: float = float("nan")
    max_drawdown: float = float("nan")
    avg_turnover: float = float("nan")
    cum_return: float = float("nan")
    n_rebalances: int = 0

    def summary(self) -> dict:
        return {
            "n_rebalances": self.n_rebalances,
            "mean_rank_ic": round(self.mean_rank_ic, 4),
            "ic_ir": round(self.ic_ir, 3),
            "net_sharpe": round(self.net_sharpe, 3),
            "gross_sharpe": round(self.gross_sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "avg_turnover": round(self.avg_turnover, 3),
            "cum_return": round(self.cum_return, 4),
        }


def cross_sectional_backtest(
    panel: pd.DataFrame,
    quantiles: int = 5,
    cost_bps: float = 10.0,
    long_short: bool = True,
    periods_per_year: int = 12,
    date_col: str = "date",
    id_col: str = "id",
    score_col: str = "score",
    fwd_ret_col: str = "fwd_ret",
) -> BacktestResult:
    res = BacktestResult()
    prev_holdings: set = set()
    gross_returns: list = []

    for d, g in panel.groupby(date_col):
        g = g.dropna(subset=[score_col, fwd_ret_col])
        if len(g) < quantiles * 2:
            continue
        # quantile buckets by score (labels 0..q-1, high score = top bucket)
        try:
            g = g.assign(_q=pd.qcut(g[score_col].rank(method="first"), quantiles, labels=False))
        except ValueError:
            continue
        top = g[g["_q"] == quantiles - 1]
        bot = g[g["_q"] == 0]

        if long_short:
            port_ret = top[fwd_ret_col].mean() - bot[fwd_ret_col].mean()
            holdings = set(top[id_col]) | set(bot[id_col])
        else:
            port_ret = top[fwd_ret_col].mean() - g[fwd_ret_col].mean()  # excess vs universe
            holdings = set(top[id_col])

        # turnover = fraction of holdings that changed since last rebalance
        if prev_holdings:
            turnover = len(holdings.symmetric_difference(prev_holdings)) / max(len(holdings | prev_holdings), 1)
        else:
            turnover = 1.0
        cost = turnover * (cost_bps / 1e4)

        res.dates.append(d)
        gross_returns.append(float(port_ret))
        res.period_returns.append(float(port_ret - cost))
        res.turnover_series.append(float(turnover))
        res.ic_series.append(rank_ic(g[score_col].to_numpy(), g[fwd_ret_col].to_numpy()))
        prev_holdings = holdings

    if not res.period_returns:
        return res

    net = np.array(res.period_returns)
    gross = np.array(gross_returns)
    ics = np.array([x for x in res.ic_series if not np.isnan(x)])

    res.n_rebalances = len(net)
    res.mean_rank_ic = float(np.mean(ics)) if ics.size else float("nan")
    res.ic_ir = float(np.mean(ics) / np.std(ics, ddof=1)) if ics.size > 1 and np.std(ics, ddof=1) > 0 else float("nan")
    res.net_sharpe = sharpe(net, periods_per_year)
    res.gross_sharpe = sharpe(gross, periods_per_year)
    res.max_drawdown = max_drawdown(net)
    res.avg_turnover = float(np.mean(res.turnover_series))
    res.cum_return = float(np.prod(1 + net) - 1)
    return res
