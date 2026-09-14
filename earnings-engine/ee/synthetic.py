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
    than randomly so repeated runs are trivially diffable in tests."""
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
            }
        )
    return events
