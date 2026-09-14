"""Deterministic synthetic-demo fallback for WW-CASCADE-DATA.

Same role as `earnings-engine/ee/synthetic.py`: a seeded, clearly-labeled
fake panel so the website seam (and a human skimming the export) has
something well-formed and NON-NaN to look at with no live network
configured — unlike the live path, which honestly returns mostly-NaN
pressure on its very first run (no prior-day snapshot to diff, no
typical_volume source at all yet; see config.py's DISCLAIMER). This module
exists specifically so "what does a fully-populated pressure export look
like" has an answer before the live path can produce one for real.

NEVER mixed with the live path within one export — see export.py. The
constituent tickers reused here (config.SYNTHETIC_CONSTITUENTS) are real
tickers from this platform's own existing default cross-sectional universe
— chosen so a reader sees names they recognize from the rest of the site,
exactly the same choice `earnings-engine/ee/synthetic.py` already makes for
the same reason — but every WEIGHT, FLOW, and VOLUME number below is
fabricated on a fixed seed. `data_provenance: "synthetic-demo"` is what
tells the UI (and this docstring tells you) that this is a demo panel, not
the honest CascadeNetwork mistake this repo already made once (see
PLATFORM_REBUILD_PLAN.md's Roadblocks / src/components/VisualsClient.tsx's
top comment) of presenting fabricated fund names/holdings as if real.
"""

from __future__ import annotations

import random
from datetime import date

import pandas as pd

from .config import FUNDS, SYNTHETIC_CONSTITUENTS

SEED = 21  # arbitrary, fixed — reproducible synthetic output run to run

try:
    import sys as _sys
    from pathlib import Path as _Path

    _CASCADE_MATH_DIR = _Path(__file__).resolve().parents[2] / "quant-infra" / "cascade"
    if str(_CASCADE_MATH_DIR) not in _sys.path:
        _sys.path.insert(0, str(_CASCADE_MATH_DIR))
    from pressure import FlowEstimate  # noqa: E402
except ImportError:  # pragma: no cover - exercised only if quant-infra/cascade moves
    FlowEstimate = None  # type: ignore[assignment]


def synthetic_snapshots(
    today: date,
) -> tuple[pd.DataFrame, list, list[dict], dict[str, float]]:
    """Returns (holdings_df, flows, fund_snapshot_records, typical_volume) —
    the same four things `export._build_from_live` produces, all
    deterministic on `SEED`. Every fund holds every name in
    `SYNTHETIC_CONSTITUENTS`, with a fixed-seed weight spread per fund (so a
    name's pressure genuinely sums across all three funds, exercising the
    exact multi-fund-overlap path `pressure.py`'s own test suite requires
    — see quant-infra/cascade/tests/test_pressure.py's
    `test_name_in_twelve_funds_is_summed_across_all_of_them`)."""
    rng = random.Random(SEED)
    as_at = today.isoformat()

    holdings_rows: list[dict] = []
    flows = []
    snapshots: list[dict] = []

    for fund in FUNDS:
        raw_weights = [rng.uniform(0.05, 0.25) for _ in SYNTHETIC_CONSTITUENTS]
        total = sum(raw_weights)
        weights = [w / total for w in raw_weights]  # normalize to sum to 1.0
        for ticker, weight in zip(SYNTHETIC_CONSTITUENTS, weights):
            holdings_rows.append(
                {"product": fund.ticker, "constituent": ticker, "weight": weight, "as_at_date": as_at}
            )

        shares_prev = rng.uniform(200_000_000, 1_200_000_000)
        # A small deterministic day-over-day change — sized to be a
        # plausible fraction of a percent, same order of magnitude a real
        # single day's creation/redemption activity would be.
        pct_change = rng.uniform(-0.004, 0.004)
        shares_now = shares_prev * (1 + pct_change)
        nav = rng.uniform(50.0, 550.0)

        snapshots.append(
            {"ticker": fund.ticker, "as_at_date": as_at, "shares_outstanding": shares_now}
        )

        if FlowEstimate is not None:
            flow_dollars = (shares_now - shares_prev) * nav
            flows.append(
                FlowEstimate(
                    product=fund.ticker,
                    as_at_date=as_at,
                    flow_dollars=flow_dollars,
                    method="shares_outstanding",
                    is_proxy=False,
                )
            )

    typical_volume = {
        ticker: rng.uniform(3e8, 4e9) for ticker in SYNTHETIC_CONSTITUENTS
    }

    holdings_df = pd.DataFrame(holdings_rows, columns=["product", "constituent", "weight", "as_at_date"])
    return holdings_df, flows, snapshots, typical_volume
