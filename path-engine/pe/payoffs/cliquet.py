"""
Cliquet / forward-starting payoffs (PATH-03), basic versions.

Two structures:

1. `forward_start_payoff` — a single forward-starting vanilla: strike is set
   as a fixed multiple of the (random, path-dependent) spot observed at a
   *future* reset date rather than at inception. Nothing exotic
   mathematically (it is a vanilla struck at a random future level), but it
   is a genuinely path-dependent payoff a closed-form Black-Scholes call
   cannot price directly once the reset date is not t=0, which is why it
   belongs in a Monte Carlo payoff library.

2. `cliquet_payoff` — the standard "globally floored, locally capped and
   floored" cliquet: a fixed notional accrues the SUM of a series of local
   percentage returns between successive reset dates, each local return
   first clipped to `[local_floor, local_cap]`, and the summed total is
   itself clipped to `[global_floor, global_cap]` before being paid on the
   notional. Setting `local_cap=inf`, `local_floor=-inf` and
   `global_floor=0` recovers the simplest possible cliquet (an unbounded
   sum of local returns, floored at zero — a "globally floored, locally
   uncapped" cliquet, a common simplified textbook starting point); the
   caps/floors are independent optional knobs precisely so this basic
   version can be dialed down to that or up to the fully-capped structure
   without code changes.
"""
from __future__ import annotations

from typing import Literal, Sequence

import numpy as np

OptionType = Literal["call", "put"]


def forward_start_payoff(
    paths: np.ndarray,
    start_index: int,
    option_type: OptionType = "call",
    moneyness: float = 1.0,
) -> np.ndarray:
    """max(phi * (S_T - moneyness * S_start), 0), S_start = paths[:, start_index]."""
    S_start = paths[:, start_index]
    S_T = paths[:, -1]
    phi = 1.0 if option_type == "call" else -1.0
    return np.maximum(phi * (S_T - moneyness * S_start), 0.0)


def cliquet_payoff(
    paths: np.ndarray,
    reset_indices: Sequence[int],
    local_floor: float = -np.inf,
    local_cap: float = np.inf,
    global_floor: float = 0.0,
    global_cap: float = np.inf,
    notional: float = 1.0,
) -> np.ndarray:
    """Undiscounted per-path cliquet payoff (see module docstring).

    `reset_indices` are column indices into `paths` marking the reset
    schedule, e.g. `[0, n/4, n/2, 3n/4, n]` for quarterly resets over the
    life of the option — local returns are computed between consecutive
    entries of this list, so it must have at least 2 entries and be
    strictly increasing.
    """
    idx = np.asarray(reset_indices, dtype=int)
    if idx.size < 2:
        raise ValueError("need at least two reset indices to form one local-return period")
    if np.any(np.diff(idx) <= 0):
        raise ValueError("reset_indices must be strictly increasing")

    levels = paths[:, idx]  # (n_paths, n_resets)
    local_returns = levels[:, 1:] / levels[:, :-1] - 1.0
    local_returns = np.clip(local_returns, local_floor, local_cap)
    total_return = local_returns.sum(axis=1)
    total_return = np.clip(total_return, global_floor, global_cap)
    return notional * total_return
