"""Lagged weekly return features.

`ret_lag_k` for k=1..10. Convention (matches the earlier v0.1 prototype at
whitewater-platform/models/weekly_forecaster.py, kept because it is correct
and worth preserving): the feature row at week t is computed using prices
known no later than t's close, and the label is the *next* week's return
(week t -> t+1). So `ret_lag_1` = the return already realized over the week
ending at t (t-1 -> t) — it is called "lag 1" because it sits one return
period back from the label, not because it uses today's not-yet-known return.
`ret_lag_k` for k>1 pushes further back. All ten are fully knowable at t.

Economic rationale: short-horizon serial (anti-)correlation in weekly equity
returns — reversal at 1-2 weeks, faint continuation further back — is one of
the oldest documented cross-sectional effects (Jegadeesh 1990; Lehmann 1990).
It is weak and noisy at the single-name weekly level, which is exactly why
lags 1-10 are handed to the model as a block rather than any one lag being
hand-picked as "the" signal.

The cross-sectional RANKED version of each lag (`ret_lag_k_xrank`) is built
in features/panel.py, not here — ranking is a property of the whole week's
cross-section, not of one ticker's own time series, so it cannot be a pure
per-ticker function.
"""

from __future__ import annotations

import pandas as pd

from .registry import feature

MAX_RETURN_LAG = 10


def _register_ret_lag(k: int):
    @feature(
        name=f"ret_lag_{k}",
        version="1.0",
        lookback_weeks=k,
        rationale=(
            f"Weekly return realized {k} return-period(s) before the label window — "
            "short-horizon serial (anti-)correlation in cross-sectional weekly returns."
        ),
    )
    def _fn(base: pd.DataFrame, _k=k) -> pd.Series:
        return base["ret"].shift(_k - 1)

    _fn.__name__ = f"ret_lag_{k}"
    return _fn


# Registers ret_lag_1 .. ret_lag_10 at import time.
for _k in range(1, MAX_RETURN_LAG + 1):
    _register_ret_lag(_k)

RET_LAG_COLUMNS = [f"ret_lag_{k}" for k in range(1, MAX_RETURN_LAG + 1)]
