"""Deterministic synthetic earnings-calendar fallback.

Same role as fac/synthetic.py / wf/synthetic.py / chaos-engine's synthetic
path: a seeded, clearly-labeled fake panel so the website seam has
something well-formed to read even with no FMP_API_KEY configured. NEVER
mixed with the live path within one export — see export.py.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from .config import UNIVERSE, LOOKAHEAD_DAYS

SEED = 21  # arbitrary, fixed — reproducible synthetic output run to run


def _synthetic_eps_estimate(ticker: str, today: date) -> float:
    """A deterministic-per-(ticker, today) fake consensus EPS estimate.

    Added 2026-09-14 alongside ee/revisions.py. Every OTHER field in this
    module (report_date, session) is already synthetic-fake and already
    deterministic per `today` via the module-level SEED; eps_estimate was
    the one field left honestly None here even though it isn't a Tier-B
    field (see the comment on the dict below) — because before
    ee/revisions.py existed, there was nothing downstream that needed a
    synthetic-demo run to have ANY estimate value, fake or otherwise.

    Now there is: revision momentum needs a real, own-history snapshot log
    to compare against, in EITHER live or synthetic-demo mode (see
    revisions.py's module docstring) — and a synthetic-demo export that
    permanently carried eps_estimate=None would make revision_direction
    permanently abstain for a structurally different reason ("no estimate
    this run") than the one this feature actually exists to demonstrate
    ("insufficient history yet, which resolves itself after a second real
    run"). Demo mode should let a reader actually SEE the "second real run"
    case, not just the "no data at all" case forever.

    This is still clearly, structurally fake data — nothing pretends
    otherwise. It's seeded from (SEED, ticker, today) via a plain SHA-256
    digest rather than Python's global `random.Random(SEED)` sequence (used
    for report_date/session above) specifically so the VALUE drifts from
    day to day for a fixed ticker (a real consensus estimate does move day
    to day) while staying perfectly reproducible for a given (ticker,
    today) pair — required so `test_deterministic` (two calls with the
    SAME `today`) keeps passing, and so running this engine on two
    different simulated days produces two different-but-stable numbers,
    which is exactly what's needed to demo a real (if synthetic-sourced)
    revision computation without waiting for actual calendar days to pass.
    Every event carrying this value is still labeled
    "data_provenance": "synthetic-demo" at the top level of the export —
    this function does not, and cannot, make a synthetic export look real.
    """
    digest = hashlib.sha256(f"{SEED}:{ticker}:{today.isoformat()}".encode()).hexdigest()
    local_rng = random.Random(int(digest[:16], 16))
    return round(local_rng.uniform(0.50, 5.00), 2)


def synthetic_events(today: date, universe: list[str] | None = None) -> list[dict]:
    """One synthetic upcoming print per ticker, spread across the lookahead
    window on a fixed seed. `session` alternates deterministically rather
    than randomly so repeated runs are trivially diffable in tests.

    `eps_estimate` is a deterministic-per-day synthetic value (see
    `_synthetic_eps_estimate` above) — added 2026-09-14 so revision-
    momentum (ee/revisions.py) has something real, if synthetic-sourced, to
    compute against in demo mode too, not only once a live estimates
    adapter exists.

    Tier-B fields (eps_estimate_stdev, sue, sue_abstain_reason,
    estimate_source) are present with the SAME honest-null shape export.py
    gives a live event with no configured/working estimates adapter —
    every event from this function is synthetic-demo already, so layering
    a second kind of fakeness (a made-up estimate stdev) on top of it would
    contradict the one rule this whole file exists to keep: synthetic data
    stays visibly, structurally inert, never dressed up to look real. This
    does NOT extend to eps_estimate itself the same way it does to the
    Tier-B fields — see `_synthetic_eps_estimate`'s docstring for why a
    single fake headline number (already alongside an already-fake
    report_date/session) is a different, narrower kind of "dressed up"
    than fabricating a derived statistical field like a surprise stdev or
    a SUE value would be."""
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
                "eps_estimate": _synthetic_eps_estimate(ticker, today),
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
