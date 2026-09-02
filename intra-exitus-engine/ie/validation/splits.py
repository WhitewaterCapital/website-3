"""Purged + embargoed walk-forward cross-validation.

Ordinary k-fold CV is invalid here for two compounding reasons:

  1. **Time.** Training on the future to predict the past is leakage. Folds must
     chain forward: train on the past, test on a later block.
  2. **Forward labels.** Our regime label at time t is computed from returns over
     [t, t+H] (see regime/labels.py). A training sample whose forward window
     reaches into the test block has, in effect, *seen* the test period. It must
     be **purged**. An additional **embargo** drops a few extra days before the
     test block so residual serial correlation can't leak either.

This splitter therefore keeps a training sample at trading-day position p only if

        p + horizon + embargo  <  first test position

i.e. its entire label window (plus the embargo buffer) closes before the test
block opens. That single inequality is the whole guarantee, and it is asserted
directly in the tests.

Pooling: several tickers share one trading calendar, so we rank samples by their
position in the *unique sorted dates*. A given date is therefore always wholly in
train or wholly in test — never split across the boundary — which is what we want
when tickers are pooled.
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
    horizon  : the label's forward window H, in trading days — the purge distance.
    embargo  : extra trading days dropped from the end of train, after purging.
    min_train : minimum unique training days required for a fold to be emitted.

    FIX #4 (2026-08): `horizon` MUST equal the label's forward horizon
    (LabelConfig.horizon). If it is smaller, the purge is too short and a training
    label's forward window can silently overlap the test block. Call sites derive
    it from the LabelConfig rather than hardcoding a value; test_splits.py checks
    the label-window-vs-test-block overlap directly, not just the splitter's own
    inequality.
    """

    n_splits: int = 5
    horizon: int = 10
    embargo: int = 5
    min_train: int = 252

    def split(self, times) -> list[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) integer-position arrays into `times`.

        `times` is an array-like of datetime64 (one entry per sample; duplicates
        across pooled tickers are fine)."""
        t = pd.DatetimeIndex(pd.to_datetime(np.asarray(times)))
        uniq = t.unique().sort_values()
        n_days = len(uniq)
        if n_days < self.n_splits + 1:
            raise ValueError("not enough distinct dates for the requested n_splits")

        # Map each sample to its position in the unique-date ordering.
        pos_of_date = {d: i for i, d in enumerate(uniq)}
        sample_pos = np.array([pos_of_date[d] for d in t], dtype=int)

        # Divide the day timeline into n_splits+1 contiguous chunks; the first
        # chunk seeds the initial train set, chunks 1..n_splits are the test
        # blocks (expanding-train walk-forward, à la sklearn TimeSeriesSplit).
        bounds = np.linspace(0, n_days, self.n_splits + 2, dtype=int)

        folds: list[tuple[np.ndarray, np.ndarray]] = []
        for k in range(1, self.n_splits + 1):
            test_lo = bounds[k]
            test_hi = bounds[k + 1]  # exclusive
            if test_hi <= test_lo:
                continue
            # Purge + embargo: train days must close their label window before test.
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
        """Human-readable train/test date spans per fold (for reporting)."""
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
