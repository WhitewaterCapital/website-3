"""
Asian option payoffs (PATH-03): arithmetic and geometric averaging, fixed
and floating strike. Each function is a small pure function over a
simulated path array `paths` of shape (n_paths, n_steps + 1) — it does not
discount, discount factors are the caller's job (kept in `pe.engine.mc` /
`pe.validation` so a payoff never silently assumes a flat discount rate).

`averaging_start_index` lets the average run over only part of the path
(e.g. a forward-starting Asian, or an Asian whose averaging window begins
after an initial lockout) — default 1 excludes the initial spot S0 at
column 0 from the average, matching the usual "average of fixings after
inception" convention used by `geometric_asian_price_bs`'s n_fixings.
"""
from __future__ import annotations

from typing import Literal

import numpy as np

OptionType = Literal["call", "put"]


def _average(paths: np.ndarray, averaging_start_index: int, kind: Literal["arithmetic", "geometric"]) -> np.ndarray:
    window = paths[:, averaging_start_index:]
    if kind == "arithmetic":
        return window.mean(axis=1)
    else:
        return np.exp(np.log(window).mean(axis=1))


def arithmetic_asian_payoff(
    paths: np.ndarray,
    K: float,
    option_type: OptionType = "call",
    strike_type: Literal["fixed", "floating"] = "fixed",
    averaging_start_index: int = 1,
) -> np.ndarray:
    """Fixed strike: max(phi*(avg - K), 0). Floating strike: max(phi*(S_T - K*avg), 0)
    (K is a multiplier on the average, typically 1.0, matching the usual
    floating-strike convention)."""
    avg = _average(paths, averaging_start_index, "arithmetic")
    phi = 1.0 if option_type == "call" else -1.0
    if strike_type == "fixed":
        return np.maximum(phi * (avg - K), 0.0)
    else:
        S_T = paths[:, -1]
        return np.maximum(phi * (S_T - K * avg), 0.0)


def geometric_asian_payoff(
    paths: np.ndarray,
    K: float,
    option_type: OptionType = "call",
    strike_type: Literal["fixed", "floating"] = "fixed",
    averaging_start_index: int = 1,
) -> np.ndarray:
    avg = _average(paths, averaging_start_index, "geometric")
    phi = 1.0 if option_type == "call" else -1.0
    if strike_type == "fixed":
        return np.maximum(phi * (avg - K), 0.0)
    else:
        S_T = paths[:, -1]
        return np.maximum(phi * (S_T - K * avg), 0.0)
