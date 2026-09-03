"""SAMPLE / DEMO feature definitions -- FEAT-01 proof of concept.

These register a handful of real, well-understood, purely mechanical
feature computations (lagged returns, RSI, rolling realized volatility)
solely to exercise the feature store end to end: registration, batch panel
building, live serving, cross-sectional transforms, and manifest hashing.

This is NOT a production feature set. In this package's own tests it is
computed against `fs.synthetic`'s deterministic SAMPLE OHLCV data -- never
against a real market feed, and no economic claim is made about any value
it produces beyond "this is what the formula returns on made-up numbers".

Real production feature definitions (news, positioning, fundamentals,
factor exposures, etc.) are blocked on the real data feeds described
elsewhere in this project's requirements (DATA-01/02/03, IMP-10 through
IMP-14) -- see feature-store/README.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import FeatureDef, FeatureRegistry


def _lagged_return_compute(lag: int):
    def compute(history: pd.DataFrame) -> pd.Series:
        close = history["close"].astype(float)
        return close.pct_change(lag)

    return compute


def _rsi_compute(window: int):
    def compute(history: pd.DataFrame) -> pd.Series:
        close = history["close"].astype(float)
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.rolling(window=window, min_periods=window).mean()
        avg_loss = loss.rolling(window=window, min_periods=window).mean()

        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # avg_loss == 0 with avg_gain > 0: every move in the window was a
        # gain -- RSI's real, defined boundary value is 100, not a
        # fabricated divide-by-zero 0.
        all_gains = (avg_loss == 0.0) & (avg_gain > 0.0)
        rsi = rsi.where(~all_gains, 100.0)
        # avg_loss == 0 AND avg_gain == 0: a perfectly flat window -- RSI is
        # genuinely undefined here, not 0 and not 50; leave as NaN.
        flat = (avg_loss == 0.0) & (avg_gain == 0.0)
        rsi = rsi.where(~flat, np.nan)
        return rsi

    return compute


def _realized_vol_compute(window: int, annualize: bool = True, periods_per_year: int = 252):
    def compute(history: pd.DataFrame) -> pd.Series:
        close = history["close"].astype(float)
        ret = close.pct_change(1)
        vol = ret.rolling(window=window, min_periods=window).std(ddof=0)
        if annualize:
            vol = vol * np.sqrt(periods_per_year)
        return vol

    return compute


def register_sample_features(registry: FeatureRegistry, owner: str = "feature-store-demo") -> dict:
    """Register the SAMPLE/DEMO feature set into `registry`. Returns
    {name: FeatureDef}. Not idempotent by design -- registering twice on
    the same registry instance raises on the duplicate (name, version) key
    (see FeatureRegistry.register), the correct failure mode for accidental
    double-registration."""
    out: dict[str, FeatureDef] = {}

    for lag in (1, 5, 10):
        name = f"ret_lag_{lag}"
        out[name] = registry.register(
            FeatureDef(
                name=name,
                version="1.0.0",
                owner=owner,
                lookback=lag + 1,
                rationale=(
                    f"{lag}-period lagged simple return, close-to-close. Short-horizon "
                    "return persistence/reversal is one of the most mechanical, most "
                    "widely documented signals in cross-sectional equity data -- it is the "
                    "cheapest possible baseline any more elaborate feature has to earn its "
                    "keep against."
                ),
                missing_data_policy="treat_as_missing",
                compute=_lagged_return_compute(lag),
            )
        )

    out["rsi_14"] = registry.register(
        FeatureDef(
            name="rsi_14",
            version="1.0.0",
            owner=owner,
            lookback=15,
            rationale=(
                "14-period RSI on simple (non-Wilder-smoothed) rolling gain/loss averages. "
                "Captures whether recent moves have skewed toward gains or losses -- a "
                "standard, bounded, path-dependent overbought/oversold proxy, registered "
                "mainly to demonstrate a feature that genuinely benefits from a bounded "
                "forward-fill (a stale-but-recent RSI reading is a reasonable stand-in for a "
                "brief data gap; an old one is not)."
            ),
            missing_data_policy="forward_fill_max_age",
            max_age_periods=3,
            compute=_rsi_compute(14),
        )
    )

    out["realized_vol_20"] = registry.register(
        FeatureDef(
            name="realized_vol_20",
            version="1.0.0",
            owner=owner,
            lookback=21,
            rationale=(
                "20-period rolling realized volatility of simple returns, annualized. Vol "
                "regime is one of the most persistent, most economically grounded state "
                "variables in equities and conditions how reliable every other feature in "
                "this store is; registered with missing_data_policy='fail' to demonstrate a "
                "feature whose consumers should never silently receive a gap -- a vol "
                "estimate a model can't compute should block that model, not feed it a "
                "guess."
            ),
            missing_data_policy="fail",
            compute=_realized_vol_compute(20),
        )
    )

    return out
