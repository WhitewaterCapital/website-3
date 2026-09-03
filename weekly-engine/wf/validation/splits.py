"""Purged + embargoed walk-forward cross-validation, for weekly-cadence data.

VENDORED, not imported: this is a small, deliberately re-typed copy of the
same purged walk-forward CV design already implemented twice in this repo —
`engine/incepta/validation/splits.py::purged_walk_forward` (generator form)
and `intra-exitus-engine/ie/validation/splits.py::PurgedWalkForwardCV` (class
form, daily cadence). This engine is sealed (see README.md), so rather than
`sys.path`-reaching into `engine/` or `intra-exitus-engine/` at runtime, the
same well-tested idea is re-implemented here, adapted to weeks instead of
trading days and with its own test suite (tests/test_splits.py) rather than
trusted by citation alone. The class shape below follows
`ie/validation/splits.py::PurgedWalkForwardCV` most closely.

Ordinary k-fold CV is invalid here for two compounding reasons:
  1. **Time.** Training on the future to predict the past is leakage. Folds
     must chain forward: train on the past, test on a later block.
  2. **Forward labels.** The label at week t is the return over [t, t+H]
     (H = LABEL_HORIZON_WEEKS, here 1). A training sample whose forward
     window reaches into the test block has, in effect, seen the test
     period. It must be purged. An extra embargo (spec: one week) drops a
     few more weeks before the test block so residual weekly autocorrelation
     can't leak either.

Guarantee: a training sample at position p is kept only if
    p + horizon + embargo < first test position
i.e. its entire label window (plus the embargo buffer) closes before the test
block opens. tests/test_splits.py asserts this directly, plus the
label-window-vs-test-block overlap (the thing that actually matters, framed
independently of the splitter's own arithmetic — see FIX #4 note in the
intra-exitus-engine sibling for why that extra framing matters).

Pooling: several tickers share one weekly calendar, so samples are ranked by
their position in the unique sorted weeks. A given week is therefore always
wholly in train or wholly in test, never split across the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PurgedWalkForwardCV:
    """Forward-chaining CV with label-horizon purging and an embargo.

    Parameters
    ----------
    n_splits : number of sequential test blocks (folds).
    horizon  : the label's forward window H, in WEEKS — the purge distance.
               Must equal the label's actual forward horizon (see
               config.LABEL_HORIZON_WEEKS); if smaller, purging is too short.
    embargo  : extra weeks dropped from the end of train, after purging
               (spec: one week).
    min_train : minimum unique training weeks required for a fold to be emitted.
    """

    n_splits: int = 5
    horizon: int = 1
    embargo: int = 1
    min_train: int = 52

    def split(self, times) -> list[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) integer-position arrays into `times`.

        `times` is array-like of datetime64 (one entry per sample; duplicates
        across pooled tickers, i.e. several rows sharing the same week, are
        expected and handled)."""
        t = pd.DatetimeIndex(pd.to_datetime(np.asarray(times)))
        uniq = t.unique().sort_values()
        n_weeks = len(uniq)
        if n_weeks < self.n_splits + 1:
            raise ValueError("not enough distinct weeks for the requested n_splits")

        pos_of_week = {w: i for i, w in enumerate(uniq)}
        sample_pos = np.array([pos_of_week[w] for w in t], dtype=int)

        bounds = np.linspace(0, n_weeks, self.n_splits + 2, dtype=int)

        folds: list[tuple[np.ndarray, np.ndarray]] = []
        for k in range(1, self.n_splits + 1):
            test_lo = bounds[k]
            test_hi = bounds[k + 1]  # exclusive
            if test_hi <= test_lo:
                continue
            train_hi = test_lo - self.horizon - self.embargo  # exclusive
            if train_hi < self.min_train:
                continue
            train_idx = np.where(sample_pos < train_hi)[0]
            test_idx = np.where((sample_pos >= test_lo) & (sample_pos < test_hi))[0]
            if len(train_idx) == 0 or len(test_idx) == 0:
                continue
            folds.append((train_idx, test_idx))
        if not folds:
            raise ValueError(
                "no valid folds — check n_splits/min_train against the data length"
            )
        return folds

    def fold_date_ranges(self, times) -> list[dict]:
        """Human-readable train/test week spans per fold (for reporting)."""
        t = pd.DatetimeIndex(pd.to_datetime(np.asarray(times)))
        out = []
        for train_idx, test_idx in self.split(times):
            out.append(
                {
                    "train_start": t[train_idx].min().date(),
                    "train_end": t[train_idx].max().date(),
                    "test_start": t[test_idx].min().date(),
                    "test_end": t[test_idx].max().date(),
                    "n_train": len(train_idx),
                    "n_test": len(test_idx),
                }
            )
        return out
