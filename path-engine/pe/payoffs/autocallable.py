"""
Autocallable payoff (PATH-03), basic version: observation dates, an
autocall barrier, a coupon barrier, and a knock-in barrier settled at
maturity. This is a deliberately simplified single-underlying structure
(the "reverse convertible with autocall" shape retail structured notes are
built from), not a general autocallable-note pricing library — no memory
coupons, no worst-of basket, no early-redemption call-protection window.

Mechanics (standard, e.g. as described in Hull, "Options, Futures and Other
Derivatives", Ch. 26 on exotic/structured products, or any structured-notes
term sheet):

At each observation date except the last, if the underlying closes at or
above `autocall_barrier * S0`, the note redeems immediately, paying
`notional * (1 + coupon_rate)` at that date (one period's coupon plus
principal — "memory" of *missed* coupons at earlier non-call dates is not
modeled here, a documented simplification).

If the note survives to the final observation date (maturity):
    - if S_T >= coupon_barrier * S0: pays `notional * (1 + coupon_rate)`
      (principal plus final coupon, even though it didn't autocall — the
      coupon barrier is usually set below the autocall barrier);
    - else if the underlying ever touched/breached `knock_in_barrier * S0`
      at any point up to maturity (checked on `knock_in_monitor_idx`,
      default: every simulated step): the downside knock-in has occurred,
      and the note pays out like the underlying itself,
      `notional * S_T / S0` (the standard "you now own a short put" outcome
      — full downside participation, no further coupon);
    - else (never knocked in, but finished below the coupon barrier): the
      note simply returns principal, `notional`, with no final coupon.

Because different paths redeem at different times, this returns a
per-path `(payoff, redemption_time_index)` pair rather than a single
undiscounted array like the other payoff modules — discounting is still
the caller's job (per this package's convention, see `pe.engine.pricer`),
but here it must be done **per path** at that path's own redemption date,
not a single flat T for every path. `pe.payoffs.autocallable.discount_autocallable`
does exactly that for a flat discount rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class AutocallableResult:
    payoff: np.ndarray  # undiscounted cash amount received, per path
    redemption_index: np.ndarray  # column index into `paths`/`times` when that cash is received


def autocallable_payoff(
    paths: np.ndarray,
    obs_indices: Sequence[int],
    S0: float,
    autocall_barrier: float,
    coupon_barrier: float,
    coupon_rate: float,
    knock_in_barrier: float,
    notional: float = 1.0,
    knock_in_monitor_idx: Optional[np.ndarray] = None,
) -> AutocallableResult:
    idx = np.asarray(obs_indices, dtype=int)
    if idx.size < 1:
        raise ValueError("need at least one observation date (the maturity)")
    if np.any(np.diff(idx) <= 0):
        raise ValueError("obs_indices must be strictly increasing")

    n_paths, n_cols = paths.shape
    payoff = np.full(n_paths, np.nan)
    redemption_index = np.full(n_paths, idx[-1], dtype=int)
    alive = np.ones(n_paths, dtype=bool)

    for obs in idx[:-1]:
        level = paths[alive, obs]
        called = level >= autocall_barrier * S0
        called_full = np.zeros(n_paths, dtype=bool)
        called_full[np.where(alive)[0][called]] = True
        payoff[called_full] = notional * (1.0 + coupon_rate)
        redemption_index[called_full] = obs
        alive &= ~called_full

    if np.any(alive):
        maturity = idx[-1]
        S_T = paths[alive, maturity]
        ki_idx = np.arange(maturity + 1) if knock_in_monitor_idx is None else np.asarray(knock_in_monitor_idx, dtype=int)
        ki_idx = ki_idx[ki_idx <= maturity]
        ever_breached = np.any(paths[alive][:, ki_idx] <= knock_in_barrier * S0, axis=1)

        final_payoff = np.where(
            S_T >= coupon_barrier * S0,
            notional * (1.0 + coupon_rate),
            np.where(ever_breached, notional * S_T / S0, notional),
        )
        alive_positions = np.where(alive)[0]
        payoff[alive_positions] = final_payoff
        redemption_index[alive_positions] = maturity

    return AutocallableResult(payoff=payoff, redemption_index=redemption_index)


def discount_autocallable(result: AutocallableResult, times: np.ndarray, r: float) -> np.ndarray:
    """Flat-rate discounting of each path's cashflow back from its own
    redemption date — the per-path analogue of `exp(-r*T) * payoff` used
    everywhere else in this package, needed here because `T` itself is
    random (the redemption date)."""
    t = times[result.redemption_index]
    return np.exp(-r * t) * result.payoff
