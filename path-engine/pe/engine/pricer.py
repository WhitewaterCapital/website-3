"""
Thin wiring layer: payoff array -> discounting -> `MonteCarloResult`.

Every payoff in `pe.payoffs` is a pure function of a path array (see each
module's docstring) that returns an *undiscounted* per-path cashflow —
discounting is deliberately kept out of the payoff layer so a payoff never
has to guess a discount convention. This module is the one place that
combines a payoff with a discount factor and routes the result through
`pe.engine.mc` (which is, in turn, the only place that computes a standard
error — see `pe.types` and `pe.engine.mc` docstrings). Nothing here is
required reading to use the payoffs directly (tests routinely call
`mc_stats`/`mc_stats_antithetic` themselves), but it removes the
boilerplate for the common case and keeps `pe.validation.model_comparison`
readable.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..types import MonteCarloResult
from .mc import control_variate_adjust, mc_stats, mc_stats_antithetic

PayoffFn = Callable[[np.ndarray], np.ndarray]


def price_from_paths(
    paths: np.ndarray,
    payoff_fn: PayoffFn,
    r: float,
    T: float,
    antithetic: bool = False,
    control: Optional[tuple[PayoffFn, float]] = None,
    meta: Optional[dict] = None,
) -> MonteCarloResult:
    """Apply `payoff_fn` to `paths`, discount at flat rate `r` over `T`, and
    return a `MonteCarloResult`.

    `control`, if given, is `(control_payoff_fn, control_true_mean)` where
    `control_true_mean` is the **already-discounted** analytic value of the
    control payoff (e.g. `geometric_asian_price_bs(...)`); the discounted
    control cashflow is built the same way as the main payoff so the
    control-variate regression happens on a like-for-like (both discounted)
    basis.
    """
    disc = float(np.exp(-r * T))
    cashflow = disc * payoff_fn(paths)

    if control is not None:
        control_fn, control_true_mean = control
        control_cashflow = disc * control_fn(paths)
        return control_variate_adjust(
            cashflow, control_cashflow, control_true_mean, antithetic=antithetic, meta=meta
        )
    if antithetic:
        return mc_stats_antithetic(cashflow, meta=meta)
    return mc_stats(cashflow, meta=meta)
