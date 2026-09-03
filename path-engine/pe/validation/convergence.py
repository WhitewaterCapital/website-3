"""
Monte Carlo convergence-rate check (PATH-06): a correctly-implemented plain
Monte Carlo estimator's standard error shrinks like `1/sqrt(N)` in the
number of paths `N` — this is not a design choice, it is the Central Limit
Theorem applied to i.i.d. (or paired-antithetic, which just rescales the
constant, not the exponent) sample averages. Asserting the *exponent* is
close to -0.5 (rather than eyeballing a couple of numbers) is a much
stronger check that nothing pathological is happening (a bug that produces
correlated "paths" that are actually duplicates of each other, for
instance, converges slower than `1/sqrt(N)` and this test would catch it
where a single-N pass/fail check would not).
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from ..types import MonteCarloResult


def fit_convergence_rate(n_list: list[int], se_list: list[float]) -> float:
    """Least-squares slope of `log(se)` vs `log(n)`. For a correct plain (or
    antithetic) Monte Carlo estimator this should sit close to -0.5."""
    log_n = np.log(np.asarray(n_list, dtype=float))
    log_se = np.log(np.asarray(se_list, dtype=float))
    slope, _intercept = np.polyfit(log_n, log_se, 1)
    return float(slope)


def measure_convergence(
    pricer: Callable[[int], MonteCarloResult],
    n_list: list[int],
) -> tuple[list[float], list[float], float]:
    """Run `pricer(n)` (a zero-argument-except-n callable that returns a
    `MonteCarloResult`, i.e. `lambda n: price_something(..., n_paths=n)`,
    typically a `functools.partial`) at each `n` in `n_list` and fit the
    log-log convergence slope of its reported standard error.

    Returns (prices, std_errors, slope).
    """
    prices: list[float] = []
    ses: list[float] = []
    for n in n_list:
        result = pricer(n)
        prices.append(result.price)
        ses.append(result.std_error)
    slope = fit_convergence_rate(n_list, ses)
    return prices, ses, slope
