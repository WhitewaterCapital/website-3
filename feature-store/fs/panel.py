"""Batch panel builder -- FEAT-01.

Spec: "Compute the panel as a dated table indexed by security and date.
Never compute features inside a training script. A feature that exists in
two places will diverge."

`build_panel` is the ONLY place this package computes a per-security
feature's batch values. It calls each registered `FeatureDef.compute` --
never a re-derivation of it -- once per security over that security's
whole point-in-time history, then applies that same `FeatureDef`'s own
missing-data policy (missing_data.apply_missing_data_policy) before
writing the result into the panel.

Point-in-time discipline: `compute()` is required (by convention -- see
registry.py's docstring, and enforced by
tests/test_batch_live_parity.py) to be non-anticipative, i.e. its value at
row `t` must not change if rows after `t` are appended to its input. Given
that, computing the whole series once and then reading off any date `t` is
identical to computing it fresh over history truncated at `t` -- which is
exactly what live.py does. This is why `load_history` is allowed (indeed
expected, for a realistic loader) to return history extending well beyond
the panel's requested date range: point-in-time safety comes from
`compute()` never looking forward within whatever frame it's handed, not
from this function pre-truncating that frame. `build_panel` cannot verify
a `compute()` function actually honors that on its own -- that is what
tests/test_batch_live_parity.py checks, for every registered feature, by
construction.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

from .missing_data import apply_missing_data_policy
from .registry import FeatureDef, FeatureRegistry

LoadHistory = Callable[[str], pd.DataFrame]


def build_panel(
    registry: FeatureRegistry,
    universe: Iterable[str],
    dates: Iterable,
    load_history: LoadHistory,
    feature_names: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Build the dated (security, date) feature panel.

    Args:
        registry: the FeatureRegistry holding every `FeatureDef` to compute.
            Only `kind="per_security"` features belong here -- cross-
            sectional features are added afterwards, on top of this panel,
            by `cross_sectional.add_cross_sectional_column` (they need the
            whole date's cross-section, which does not exist until this
            function has already produced it).
        universe: security identifiers to build rows for.
        dates: the panel's dates. Need not be contiguous or evenly spaced;
            each is looked up independently against each security's
            computed series.
        load_history: `load_history(security) -> pd.DataFrame`, an
            ascending, duplicate-free DatetimeIndex frame (e.g. OHLCV) for
            `security`. It may (and typically will) return more history
            than the requested `dates` span -- that's normal and safe, see
            "Point-in-time discipline" above. It must never omit a row
            dated on or before any requested date that genuinely exists,
            though: every requested date must be present in the index (see
            below).
        feature_names: restrict to these registered feature names; None
            means every `kind="per_security"` feature in the registry.

    Returns:
        A DataFrame with a (security, date) MultiIndex and one column per
        feature, values NaN wherever missing under that feature's policy
        ("fail" features never leave NaN in the returned frame -- they
        raise instead, at the missing-data policy stage, per-security).
    """
    dates = sorted(pd.Timestamp(d) for d in dates)
    if not dates:
        raise ValueError("build_panel requires at least one date")
    universe = list(universe)
    if not universe:
        raise ValueError("build_panel requires a non-empty universe")

    if feature_names is not None:
        defs = [registry.get(n) for n in feature_names]
    else:
        defs = [fd for fd in registry.list() if fd.kind == "per_security"]

    per_security_frames = []
    for security in universe:
        history = load_history(security)
        if not isinstance(history, pd.DataFrame):
            raise TypeError(f"load_history({security!r}) must return a pandas DataFrame")
        if not history.index.is_monotonic_increasing:
            raise ValueError(f"load_history({security!r}) must return data sorted ascending by date")
        if history.index.has_duplicates:
            raise ValueError(f"load_history({security!r}) returned duplicate dates")
        missing_dates = [d for d in dates if d not in history.index]
        if missing_dates:
            # Reindexing onto a date the history doesn't have at all would
            # silently introduce a NaN AFTER the missing-data policy check
            # below has already run -- which would let a "fail" policy
            # feature slip a missing value past the very check that's
            # supposed to catch it. Refuse instead: the caller must supply
            # `dates` that are actually in this security's own calendar.
            raise ValueError(
                f"requested date(s) not present in load_history({security!r})'s index: "
                f"{[d.date() for d in missing_dates[:5]]}"
                + (" ..." if len(missing_dates) > 5 else "")
            )

        columns = {}
        for fd in defs:
            raw = fd.compute(history)
            if not isinstance(raw, pd.Series):
                raise TypeError(
                    f"feature {fd.name!r} compute() must return a pandas Series for batch "
                    f"panel building, got {type(raw).__name__}"
                )
            raw = raw.reindex(history.index)
            filled = apply_missing_data_policy(raw, fd)
            columns[fd.name] = filled.reindex(dates)  # NaN for any requested date not in history

        frame = pd.DataFrame(columns, index=pd.Index(dates, name="date"))
        frame.insert(0, "security", security)
        per_security_frames.append(frame.reset_index())

    panel = pd.concat(per_security_frames, ignore_index=True)
    panel = panel.set_index(["security", "date"]).sort_index()
    return panel
