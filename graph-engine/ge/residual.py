"""The tradeable object: actual signal minus what the graph implied it should
be.

    residual        = actual_signal - diffused_neighbourhood_implied_signal
    residual_z      = residual, cross-sectionally standardized (this date's names)
    residual_z_sector_neutral = residual_z, sector mean subtracted per sector

A large POSITIVE residual is a name that ran away from its (graph) group — its
own signal is well above what its neighbours implied. A large NEGATIVE residual
is a name left behind. That's a pairs-style statistical divergence, and it is
exactly what `reversion.py` then checks for actual mean reversion before this
is ever treated as tradeable (see that module + README "done when" bar).

Sector neutrality: the diffusion + sector prior already pulls same-sector
names toward each other, but a residual can still carry a sector-wide tilt
(e.g. every name in a hot sector "ran away" together, which is a sector call,
not a pairs-style idiosyncratic divergence). Subtracting the same-sector mean
of `residual_z` removes that common component, leaving only the
within-sector, name-specific divergence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import DiffusionConfig
from .graph.diffusion import diffuse


@dataclass(frozen=True)
class ResidualFrame:
    tickers: list[str]
    signal: np.ndarray
    diffused: np.ndarray
    residual: np.ndarray
    residual_z: np.ndarray
    residual_z_sector_neutral: np.ndarray

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ticker": self.tickers,
                "signal": self.signal,
                "diffused": self.diffused,
                "residual": self.residual,
                "residual_z": self.residual_z,
                "residual_z_sector_neutral": self.residual_z_sector_neutral,
            }
        )


def _zscore(x: np.ndarray) -> np.ndarray:
    finite = x[np.isfinite(x)]
    if finite.size < 2:
        return np.zeros_like(x)
    mu = finite.mean()
    sd = finite.std(ddof=0)
    if not np.isfinite(sd) or sd <= 0:
        return np.zeros_like(x)
    return (x - mu) / sd


def _sector_neutralize(residual_z: np.ndarray, tickers: list[str], sector_of: dict[str, str]) -> np.ndarray:
    sectors = np.array([sector_of[t] for t in tickers], dtype=object)
    out = residual_z.copy()
    for sec in pd.unique(sectors):
        m = sectors == sec
        if m.sum() == 0:
            continue
        out[m] = residual_z[m] - np.nanmean(residual_z[m])
    return out


def compute_residuals(
    signal: pd.Series,
    sparse_weights: np.ndarray,
    sector_of: dict[str, str],
    cfg: DiffusionConfig = DiffusionConfig(),
) -> ResidualFrame:
    """One cross-section: `signal` indexed by ticker (same order/tickers as
    `sparse_weights`'s rows/cols), diffused across `sparse_weights`."""
    tickers = list(signal.index)
    s = signal.to_numpy(dtype=float)
    if np.any(~np.isfinite(s)):
        raise ValueError("signal must be finite for every name in this cross-section")

    diffused = diffuse(s, sparse_weights, cfg)
    residual = s - diffused
    residual_z = _zscore(residual)
    residual_z_neutral = _sector_neutralize(residual_z, tickers, sector_of)

    return ResidualFrame(
        tickers=tickers,
        signal=s,
        diffused=diffused,
        residual=residual,
        residual_z=residual_z,
        residual_z_sector_neutral=residual_z_neutral,
    )
