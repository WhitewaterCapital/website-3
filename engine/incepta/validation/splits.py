"""Leakage-safe time-series splits (López de Prado 2018).

Random k-fold leaks the future in finance because labels are forward-looking and
overlap in time. These splitters:
  - **purge** training samples whose label window overlaps the test window, and
  - **embargo** a buffer immediately after the test window,
so information cannot bleed from test into train. Indices are positional (0..N-1),
assumed sorted in time.
"""

from __future__ import annotations

import numpy as np


def purged_walk_forward(
    n_samples: int,
    n_splits: int = 5,
    label_horizon: int = 1,
    min_train: int = None,
):
    """Expanding-window walk-forward. Train is always the PAST; samples whose
    label [i, i+label_horizon] reaches into the test block are purged.
    Yields (train_idx, test_idx) numpy arrays.
    """
    if min_train is None:
        min_train = n_samples // (n_splits + 1)
    test_region = np.arange(min_train, n_samples)
    blocks = np.array_split(test_region, n_splits)
    for block in blocks:
        if block.size == 0:
            continue
        test_start = int(block[0])
        test_idx = block
        # train = strictly before test_start, minus the purge zone
        train_end = test_start - label_horizon
        train_idx = np.arange(0, max(train_end, 0))
        if train_idx.size == 0:
            continue
        yield train_idx, test_idx


def purged_kfold(
    n_samples: int,
    n_splits: int = 5,
    label_horizon: int = 1,
    embargo: int = 0,
):
    """K-fold where each fold is a contiguous test block and the train set removes
    [test_start - label_horizon, test_end + embargo]. Yields (train, test).
    """
    folds = np.array_split(np.arange(n_samples), n_splits)
    for fold in folds:
        if fold.size == 0:
            continue
        test_start, test_end = int(fold[0]), int(fold[-1])
        lo = test_start - label_horizon
        hi = test_end + embargo
        mask = np.ones(n_samples, dtype=bool)
        mask[max(lo, 0): hi + 1] = False
        train_idx = np.where(mask)[0]
        yield train_idx, fold
