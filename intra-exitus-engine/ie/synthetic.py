"""Deterministic synthetic daily prices — the demo fallback this engine uses
when no live price key (`TIINGO_API_KEY`) is configured.

Purpose, and its one hard rule: this exists so the website seam
(`public/data/intra-exitus/latest.json`) and the ORCH-01 equity clock have
something to read with no outbound network access and no API key — exactly the
same demo-mode fallback `factor-engine/fac/synthetic.py` already provides for
its own export. Anything built from this module is permanently labeled
`"data_provenance": "synthetic-demo"` wherever it surfaces (see
`export.py`); it must never be mistaken for a real market read.

Model: an independent geometric-Brownian-motion close path per ticker
(per-ticker fixed seed, so the whole panel is byte-for-byte reproducible),
with OHLC wrapped around each close by a small deterministic intraday range
and a lognormal volume. It deliberately does NOT imitate real cross-name
correlation, real drift, or real volatility term structure — its only job is
to exercise the regime classifier + level/pipeline code end to end with a
stable, honest, clearly-fake series. A ticker with no clean setup still comes
back as an abstain plan downstream, never a fabricated level.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .pit import PriceBar

# A fixed, settled end date keeps the demo export deterministic (so the clock
# commits nothing when nothing changed) rather than drifting with wall-clock
# "today". Honest for a synthetic-demo series: it is a fixed illustrative panel,
# not a live feed.
SYNTHETIC_END = date(2024, 12, 31)

# Per-ticker "personality" (annualised drift, annualised vol, starting price).
# Fixed and documented, fit to nothing — just enough spread to give the regime
# classifier distinct trend/vol regimes to separate.
_PROFILE: dict[str, dict[str, float]] = {
    "AAPL": {"mu": 0.14, "sigma": 0.26, "p0": 90.0},
    "MSFT": {"mu": 0.13, "sigma": 0.24, "p0": 180.0},
    "NVDA": {"mu": 0.30, "sigma": 0.48, "p0": 25.0},
    "KO": {"mu": 0.05, "sigma": 0.15, "p0": 45.0},
    "F": {"mu": 0.03, "sigma": 0.35, "p0": 12.0},
}
_DEFAULT_PROFILE = {"mu": 0.08, "sigma": 0.28, "p0": 50.0}

_TRADING_DAYS = 252


def _seed_for(ticker: str) -> int:
    """A stable per-ticker seed so a given ticker always yields the same path."""
    return abs(hash(("ie-synthetic", ticker.upper()))) % (2**32)


class SyntheticPriceClient:
    """Drop-in stand-in for `adapters.prices_tiingo.TiingoClient` — same
    `fetch_prices(ticker, start, end)` shape, returning `list[PriceBar]`."""

    name = "synthetic-demo"

    def fetch_prices(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> list[PriceBar]:
        start = start or date(2010, 1, 1)
        end = min(end or SYNTHETIC_END, SYNTHETIC_END)
        days = pd.bdate_range(start=pd.Timestamp(start), end=pd.Timestamp(end))
        if len(days) == 0:
            return []

        prof = _PROFILE.get(ticker.upper(), _DEFAULT_PROFILE)
        rng = np.random.default_rng(_seed_for(ticker))

        dt = 1.0 / _TRADING_DAYS
        mu, sigma, p0 = prof["mu"], prof["sigma"], prof["p0"]
        shocks = rng.standard_normal(len(days))
        log_rets = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks
        closes = p0 * np.exp(np.cumsum(log_rets))

        # Deterministic intraday range + volume around each close.
        intraday = np.abs(rng.standard_normal(len(days))) * sigma * np.sqrt(dt)
        volumes = np.exp(rng.normal(np.log(5_000_000), 0.4, len(days)))

        bars: list[PriceBar] = []
        prev_close = p0
        for i, ts in enumerate(days):
            close = float(closes[i])
            rng_amp = close * float(intraday[i])
            high = max(prev_close, close) + rng_amp
            low = min(prev_close, close) - rng_amp
            open_ = float(prev_close)
            bars.append(
                PriceBar(
                    ticker=ticker.upper(),
                    date=ts.date(),
                    open=round(open_, 4),
                    high=round(high, 4),
                    low=round(max(low, 0.01), 4),
                    close=round(close, 4),
                    volume=round(float(volumes[i]), 1),
                    source=self.name,
                    adjusted=True,
                    ingested_at=end,
                )
            )
            prev_close = close
        return bars
