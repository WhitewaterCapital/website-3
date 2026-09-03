"""
Lookback option payoffs (PATH-03): fixed and floating strike, running
max/min taken over the whole simulated path (all columns, including S0 at
column 0 — the standard convention: the "lookback period" is the option's
entire life, so the initial spot is itself an eligible extremum).
"""
from __future__ import annotations

from typing import Literal

import numpy as np

OptionType = Literal["call", "put"]
StrikeType = Literal["fixed", "floating"]


def lookback_payoff(
    paths: np.ndarray,
    option_type: OptionType,
    strike_type: StrikeType,
    K: float | None = None,
) -> np.ndarray:
    """Undiscounted per-path lookback payoff.

    Floating strike:
        call = S_T - running_min       (buy at the historical low)
        put  = running_max - S_T       (sell at the historical high)
        (`K` is ignored/must be None — the strike floats with the path.)

    Fixed strike (`K` required):
        call = max(running_max - K, 0)
        put  = max(K - running_min, 0)
    """
    running_max = paths.max(axis=1)
    running_min = paths.min(axis=1)
    S_T = paths[:, -1]

    if strike_type == "floating":
        if K is not None:
            raise ValueError("floating-strike lookback does not take a fixed K")
        if option_type == "call":
            return S_T - running_min
        return running_max - S_T

    if K is None:
        raise ValueError("fixed-strike lookback requires K")
    if option_type == "call":
        return np.maximum(running_max - K, 0.0)
    return np.maximum(K - running_min, 0.0)
