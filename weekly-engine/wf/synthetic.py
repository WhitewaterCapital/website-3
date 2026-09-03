"""Synthetic weekly OHLCV panel generator — for tests AND the demo export.

No real point-in-time weekly price history is available in this sandbox (see
README.md's "what a real run needs"), so this is the ONLY data source
wf/export.py can use here; it is clearly marked as such in the export's
`provenance` field, never presented as real.

The generator's key feature is `signal_strength`: a knob that embeds a
genuine, slow-moving, honestly-causal predictive relationship into the
synthetic returns (or, at 0.0, embeds none at all). This is what makes the
two halves of tests/test_validation_harness.py possible:

  * `signal_strength=0.0`  -> a pure random walk. No feature, however
    constructed, has any real information about next week's return. This is
    the "no signal" fixture: the harness must report near-zero rank IC and
    must NOT claim GBM beats baseline.
  * `signal_strength>0.0`  -> each ticker has a persistent AR(1) latent
    factor; next week's return is `signal_strength * latent[t] + noise`,
    where `latent` evolves slowly (phi close to 1). Because `latent` is
    persistent, PAST returns (which also depend on `latent`) are
    statistically informative about its CURRENT level, and therefore about
    NEXT week's return — without any row using information from its own
    future. This is a real, causal, if weak and noisy, predictive
    relationship — not a shortcut/leak. It is deliberately weak: the
    strengths used in tests/export are calibrated to land in the "genuinely
    good" 0.02-0.05 OOS rank IC band the spec calls out, not far above it
    (which the spec explicitly says to treat as a leak, not an edge).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_START = "2015-01-02"


def generate_synthetic_weekly_prices(
    tickers: list[str],
    n_weeks: int = 260,
    seed: int = 0,
    signal_strength: float = 0.0,
    latent_phi: float = 0.92,
    latent_noise_std: float = 0.35,
    idio_noise_std: float = 0.028,
    start: str = DEFAULT_START,
) -> dict[str, pd.DataFrame]:
    """Return {ticker: weekly OHLCV DataFrame} with columns close/volume,
    indexed by a shared weekly (Friday) DatetimeIndex.

    Each ticker gets its own independent latent AR(1) path and its own RNG
    stream (seeded off the global `seed` + a per-ticker offset), so tickers
    are cross-sectionally independent except through the shared calendar —
    which is what lets the cross-sectional (rank/z-score/decile) machinery
    have something non-degenerate to work with.
    """
    dates = pd.bdate_range(start, periods=n_weeks, freq="W-FRI")
    out: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        rng = np.random.default_rng(seed * 10_000 + i)
        latent = np.zeros(n_weeks)
        latent[0] = rng.normal()
        for t in range(1, n_weeks):
            latent[t] = latent_phi * latent[t - 1] + rng.normal(scale=latent_noise_std)
        idio = rng.normal(scale=idio_noise_std, size=n_weeks)
        ret = signal_strength * 0.02 * latent + idio
        # A little cross-sectional heterogeneity in starting level/volume so
        # names aren't literal clones of each other's price scale.
        start_price = 20.0 + 10.0 * rng.random()
        close = start_price * np.cumprod(1.0 + ret)
        base_vol = 1_000_000 * (0.5 + rng.random())
        volume = base_vol * (1.0 + 0.25 * rng.normal(size=n_weeks)).clip(min=0.1)
        out[ticker] = pd.DataFrame({"close": close, "volume": volume}, index=dates)
    return out


def default_sector_map(tickers: list[str], n_sectors: int = 4) -> dict[str, str]:
    """A simple round-robin sector assignment for synthetic universes that
    don't need config.SECTOR_MAP's real tags (tests mostly)."""
    return {t: f"sector_{i % n_sectors}" for i, t in enumerate(tickers)}


def generate_regime_dependent_signal_prices(
    tickers: list[str],
    n_weeks: int = 320,
    seed: int = 0,
    strength: float = 1.0,
    latent_phi: float = 0.92,
    latent_noise_std: float = 0.35,
    idio_noise_std_low_vol: float = 0.012,
    idio_noise_std_high_vol: float = 0.05,
    start: str = DEFAULT_START,
) -> dict[str, pd.DataFrame]:
    """A second, deliberately NONLINEAR synthetic fixture, used only by
    tests/test_validation_harness.py to exercise the "GBM genuinely beats
    ridge" path.

    `generate_synthetic_weekly_prices`'s embedded signal is linear in the
    latent factor, which is exactly the shape ridge on ranked features is
    built to catch — so it is a poor fixture for proving a tree model can
    ever legitimately win. This generator instead embeds momentum
    persistence that is REGIME-DEPENDENT: a second, independent, persistent
    latent process sets the week's idiosyncratic noise level, and momentum
    only carries predictive power in the LOW-noise ("clean trend") regime —
    in the high-noise regime the same momentum reading carries none. This is
    a real, well-documented empirical pattern (momentum/trend signals work
    better in calm markets than in noisy/choppy ones), and it is exactly the
    kind of interaction a shallow tree can exploit by splitting on realized
    volatility (vol_10, a feature the model has) before conditioning on
    momentum — while a model linear in ranked features, which must apply one
    global coefficient to momentum across both regimes, dilutes it by
    averaging over a regime where momentum means nothing.
    """
    dates = pd.bdate_range(start, periods=n_weeks, freq="W-FRI")
    out: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        rng = np.random.default_rng(seed * 10_000 + i)
        mom_latent = np.zeros(n_weeks)
        mom_latent[0] = rng.normal()
        vol_latent = np.zeros(n_weeks)
        vol_latent[0] = rng.normal()
        for t in range(1, n_weeks):
            mom_latent[t] = latent_phi * mom_latent[t - 1] + rng.normal(scale=latent_noise_std)
            vol_latent[t] = latent_phi * vol_latent[t - 1] + rng.normal(scale=latent_noise_std)

        ret = np.zeros(n_weeks)
        for t in range(n_weeks):
            low_vol_regime = vol_latent[t - 1] < 0 if t > 0 else True
            noise_std = idio_noise_std_low_vol if low_vol_regime else idio_noise_std_high_vol
            eff_strength = strength * 0.02 if low_vol_regime else 0.0
            mom_input = mom_latent[t - 1] if t > 0 else 0.0
            ret[t] = eff_strength * mom_input + rng.normal(scale=noise_std)

        start_price = 20.0 + 10.0 * rng.random()
        close = start_price * np.cumprod(1.0 + ret)
        base_vol = 1_000_000 * (0.5 + rng.random())
        volume = base_vol * (1.0 + 0.25 * rng.normal(size=n_weeks)).clip(min=0.1)
        out[ticker] = pd.DataFrame({"close": close, "volume": volume}, index=dates)
    return out
