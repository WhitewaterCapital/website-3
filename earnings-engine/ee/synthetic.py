"""Deterministic synthetic earnings-calendar fallback.

Same role as fac/synthetic.py / wf/synthetic.py / chaos-engine's synthetic
path: a seeded, clearly-labeled fake panel so the website seam has
something well-formed to read even with no FMP_API_KEY configured. NEVER
mixed with the live path within one export — see export.py.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .config import UNIVERSE, LOOKAHEAD_DAYS

SEED = 21  # arbitrary, fixed — reproducible synthetic output run to run


def synthetic_events(today: date, universe: list[str] | None = None) -> list[dict]:
    """One synthetic upcoming print per ticker, spread across the lookahead
    window on a fixed seed. `session` alternates deterministically rather
    than randomly so repeated runs are trivially diffable in tests.

    Tier-B fields (eps_estimate_stdev, sue, sue_abstain_reason,
    estimate_source) are present with the SAME honest-null shape export.py
    gives a live event with no configured/working estimates adapter —
    every event from this function is synthetic-demo already, so layering
    a second kind of fakeness (a made-up estimate stdev) on top of it would
    contradict the one rule this whole file exists to keep: synthetic data
    stays visibly, structurally inert, never dressed up to look real."""
    universe = universe if universe is not None else UNIVERSE
    rng = random.Random(SEED)
    events = []
    for i, ticker in enumerate(universe):
        offset = rng.randint(1, LOOKAHEAD_DAYS)
        report_date = today + timedelta(days=offset)
        session = "amc" if i % 2 == 0 else "bmo"
        events.append(
            {
                "ticker": ticker,
                "report_date": report_date.isoformat(),
                "session": session,
                "eps_estimate": None,
                "eps_actual": None,
                "fiscal_period": None,
                "source": "synthetic-demo",
                "eps_estimate_stdev": None,
                "estimate_source": None,
                "sue": None,
                "sue_abstain_reason": "synthetic-demo event — no real estimate data attached by design",
            }
        )
    return events
