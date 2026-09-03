"""Cost-aware backtest of the residual as a standalone signal.

Self-contained (no import from `engine/incepta/backtest/engine.py` — this
engine is sealed) but the same idea: a long panel of one row per (date,
ticker) with a fade `score` known at that date and a `fwd_ret` realized over
the following `horizon` trading days (1-10, per the spec). At each date we
long the bottom-`quantile` names by `score` and short the top-`quantile`
names... actually simpler and less error-prone to get right: we sort by
`score` and go long the HIGH-score names, short the LOW-score names, exactly
like a standard long/short quantile backtest. The caller decides what "high
score" means — for fading a residual, pass `score = -residual_z` (see
`reversion.py`/README): a large negative residual (name left behind) gets a
large positive fade score (a long candidate), a large positive residual (name
that ran away) gets a large negative fade score (a short candidate).

Costs are charged on TURNOVER (the fraction of the long/short book that
changed since the previous rebalance) at `cost_bps` per unit turnover —
the standard cost-aware backtest idiom (mirrors the shape of
`engine/incepta/backtest/engine.py::cross_sectional_backtest`, rewritten
standalone here).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BacktestConfig


def _rank_ic(score: np.ndarray, fwd_ret: np.ndarray) -> float:
    """Spearman rank correlation, computed by hand (no scipy.stats dependency
    needed for a plain Pearson-on-ranks calculation)."""
    if score.size < 3:
        return float("nan")
    sr = pd.Series(score).rank().to_numpy()
    rr = pd.Series(fwd_ret).rank().to_numpy()
    if np.std(sr) == 0 or np.std(rr) == 0:
        return float("nan")
    return float(np.corrcoef(sr, rr)[0, 1])


def _sharpe(returns: np.ndarray, periods_per_year: int) -> float:
    if returns.size < 2 or np.std(returns, ddof=1) == 0:
        return float("nan")
    return float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(periods_per_year))


def _max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return float("nan")
    curve = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(curve)
    dd = curve / peak - 1.0
    return float(dd.min())


@dataclass
class BacktestResult:
    dates: list = field(default_factory=list)
    period_returns: list = field(default_factory=list)  # net of cost
    gross_returns: list = field(default_factory=list)
    ic_series: list = field(default_factory=list)
    turnover_series: list = field(default_factory=list)
    mean_rank_ic: float = float("nan")
    net_sharpe: float = float("nan")
    gross_sharpe: float = float("nan")
    max_drawdown: float = float("nan")
    avg_turnover: float = float("nan")
    cum_return: float = float("nan")
    n_rebalances: int = 0

    def summary(self) -> dict:
        return {
            "n_rebalances": self.n_rebalances,
            "mean_rank_ic": round(self.mean_rank_ic, 4) if np.isfinite(self.mean_rank_ic) else None,
            "net_sharpe": round(self.net_sharpe, 3) if np.isfinite(self.net_sharpe) else None,
            "gross_sharpe": round(self.gross_sharpe, 3) if np.isfinite(self.gross_sharpe) else None,
            "max_drawdown": round(self.max_drawdown, 4) if np.isfinite(self.max_drawdown) else None,
            "avg_turnover": round(self.avg_turnover, 3) if np.isfinite(self.avg_turnover) else None,
            "cum_return": round(self.cum_return, 4) if np.isfinite(self.cum_return) else None,
        }


def backtest_residual(
    panel: pd.DataFrame,
    cfg: BacktestConfig = BacktestConfig(),
    date_col: str = "date",
    id_col: str = "ticker",
    score_col: str = "score",
    fwd_ret_col: str = "fwd_ret",
) -> BacktestResult:
    """`panel` must already have `fwd_ret_col` computed over `cfg.horizon`
    trading days starting AFTER `date_col` (point-in-time; the caller's
    responsibility, exactly as in the Incepta backtest engine)."""
    res = BacktestResult()
    prev_holdings: set = set()

    for d, g in panel.groupby(date_col):
        g = g.dropna(subset=[score_col, fwd_ret_col])
        n = len(g)
        n_leg = max(int(round(n * cfg.quantile)), 1)
        if n < 2 * n_leg:
            continue

        g = g.sort_values(score_col)
        bottom = g.iloc[:n_leg]   # low score -> short leg
        top = g.iloc[-n_leg:]     # high score -> long leg

        port_ret = float(top[fwd_ret_col].mean() - bottom[fwd_ret_col].mean())
        holdings = set(top[id_col]) | set(bottom[id_col])

        if prev_holdings:
            turnover = len(holdings.symmetric_difference(prev_holdings)) / max(
                len(holdings | prev_holdings), 1
            )
        else:
            turnover = 1.0
        cost = turnover * (cfg.cost_bps / 1e4)

        res.dates.append(d)
        res.gross_returns.append(port_ret)
        res.period_returns.append(port_ret - cost)
        res.turnover_series.append(turnover)
        res.ic_series.append(_rank_ic(g[score_col].to_numpy(), g[fwd_ret_col].to_numpy()))
        prev_holdings = holdings

    if not res.period_returns:
        return res

    net = np.array(res.period_returns)
    gross = np.array(res.gross_returns)
    ics = np.array([x for x in res.ic_series if np.isfinite(x)])

    res.n_rebalances = len(net)
    res.mean_rank_ic = float(np.mean(ics)) if ics.size else float("nan")
    res.net_sharpe = _sharpe(net, cfg.periods_per_year)
    res.gross_sharpe = _sharpe(gross, cfg.periods_per_year)
    res.max_drawdown = _max_drawdown(net)
    res.avg_turnover = float(np.mean(res.turnover_series))
    res.cum_return = float(np.prod(1 + net) - 1)
    return res
