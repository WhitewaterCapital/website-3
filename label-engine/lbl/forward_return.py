"""Forward-return labels with an explicit alignment rule (FEAT-02).

The label for period t is the return from close of period t to close of
period t+horizon, and — this is the whole point of the module — it is not
knowable until that second close prints. So every label this module produces
carries its own `knowable_from` timestamp alongside the numeric value; there
is deliberately no function here that returns the bare number, because a
label without its knowable-from time is exactly how look-ahead gets in
(a value gets joined onto a feature row without anyone checking whether it
could actually have been known there).

Alignment convention (matches the one already established in
weekly-engine/wf/labels.py::compute_labels, generalized to an arbitrary
integer horizon): `horizon` is a number of BARS on the input series' own
index, not a fixed calendar offset. Using the index's own value at position
i+horizon — rather than "index[i] + horizon * some fixed timedelta" — is
deliberate: it is exact even when the real calendar has holidays or an
occasional short/irregular period, whereas a fixed offset could silently
understate (or overstate) the true knowable-from time. Callers with a
literal calendar horizon in mind (e.g. "1 week" on a weekly-sampled series)
pass horizon=1; a daily series predicting one week ahead passes horizon=5 (or
however many trading days the week actually had, resampled first).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ForwardReturnLabel:
    """One forward-return observation, always carrying its knowable-from time.

    Attributes:
        ref_time: the timestamp the label is *for* (period t) — this is the
            timestamp a feature row would be paired with.
        knowable_from: the timestamp at which `value` first became knowable —
            period t+horizon's own close timestamp. Strictly later than
            `ref_time` by construction (horizon >= 1).
        value: close[t+horizon] / close[t] - 1.
    """

    ref_time: Any
    knowable_from: Any
    value: float


def forward_return_labels(prices: pd.Series, horizon: int = 1) -> pd.DataFrame:
    """Vectorized forward-return labels for every period in `prices`.

    Args:
        prices: a close-price series indexed by time, sorted ascending.
        horizon: number of bars forward (>= 1). Default 1 = "next period".

    Returns:
        A DataFrame aligned to `prices.index` with columns:
          - `forward_return`: close[t+horizon]/close[t] - 1. NaN for the last
            `horizon` rows, since there is no t+horizon yet for them (those
            rows are live/current, never valid training targets).
          - `knowable_from`: the timestamp of period t+horizon itself, i.e.
            exactly when `forward_return` becomes knowable. NaT wherever
            `forward_return` is NaN.

        Every defined row satisfies `knowable_from > prices.index` at that
        row, strictly — see tests/test_forward_return.py.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1 bar (got {horizon}); horizon=0 would not be forward-looking")
    idx = prices.index
    forward_return = prices.shift(-horizon) / prices - 1.0
    # The actual timestamp of the row `horizon` bars ahead, per-row — not a
    # fixed-timedelta guess. See module docstring for why this matters.
    knowable_from = pd.Series(idx, index=idx).shift(-horizon)
    return pd.DataFrame(
        {"forward_return": forward_return, "knowable_from": knowable_from},
        index=idx,
    )


def to_records(labels: pd.DataFrame) -> list[ForwardReturnLabel]:
    """Expand a `forward_return_labels` DataFrame into `ForwardReturnLabel`
    records, dropping rows with no defined label (the trailing live rows).
    """
    defined = labels["knowable_from"].notna()
    out = []
    for ref_time, row in labels.loc[defined].iterrows():
        out.append(
            ForwardReturnLabel(
                ref_time=ref_time,
                knowable_from=row["knowable_from"],
                value=float(row["forward_return"]),
            )
        )
    return out
