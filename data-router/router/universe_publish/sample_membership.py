"""A concrete SAMPLE synthetic universe used to prove the DATA-02 mechanism.

Every ticker below is invented for this repository and does not refer to any
real, tradeable security. This is deliberate and required by the project's
data-honesty rules: a real ~300+ name equity universe needs a real index
membership vendor (S&P index files, a paid membership feed), which this
sandbox does not have and IMP-08 explicitly blocks fabricating. 10-20
synthetic names is enough to exercise every code path the real thing will
need — entry/exit dates, delisted names, a liquidity floor, and the
survivorship test — without pretending this is a production universe.

Column contract matches ``router.universe.UniverseBuilder``'s required
columns (``ticker``, ``entry_date``, ``exit_date``) plus one additional
column, ``inclusion_reason``, that DATA-02 asks every member to carry
(``UniverseBuilder`` only validates the columns it needs and ignores extra
ones, so this is a strict superset — no changes to that module were needed
or made).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# "Today" for this synthetic dataset's design purposes. Kept as a module
# constant (not datetime.today()) so the dataset's story — who is active,
# who already delisted, who IPO'd recently — stays fixed and reproducible
# regardless of when tests run.
SAMPLE_DATASET_AS_OF = date(2026, 9, 3)

UNIVERSE_NAME = "ww-sample-universe"
VENUE = "NYSE"


def sample_membership() -> pd.DataFrame:
    """Return the synthetic membership table.

    Three groups, mirroring the real universe-construction problem DATA-02
    describes:

    * ``SYN-CORE-*``    — long-tenured members, still active today.
    * ``SYN-DELIST-*``  — names that were real members and were later
      delisted (acquired / went private / bankrupt). These exist specifically
      so the survivorship test has something real to check: a query for a
      past as-of date *before* the exit date must still return the name.
    * ``SYN-IPO-*``     — names that entered the universe recently; a query
      for a date before their entry date must exclude them.
    """
    rows = [
        # --- long-tenured, still active -------------------------------------------------
        {"ticker": "SYN-CORE-01", "entry_date": date(2012, 3, 1), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-02", "entry_date": date(2013, 7, 15), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-03", "entry_date": date(2014, 1, 10), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-04", "entry_date": date(2015, 5, 20), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-05", "entry_date": date(2016, 9, 1), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-06", "entry_date": date(2017, 2, 14), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-07", "entry_date": date(2018, 11, 5), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        {"ticker": "SYN-CORE-08", "entry_date": date(2019, 6, 18), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor"},
        # --- delisted: real members of the past universe, gone since -------------------
        {"ticker": "SYN-DELIST-01", "entry_date": date(2011, 4, 1), "exit_date": date(2023, 8, 15),
         "inclusion_reason": "index_membership+liquidity_floor; delisted (acquired)"},
        {"ticker": "SYN-DELIST-02", "entry_date": date(2014, 10, 3), "exit_date": date(2024, 3, 1),
         "inclusion_reason": "index_membership+liquidity_floor; delisted (went private)"},
        {"ticker": "SYN-DELIST-03", "entry_date": date(2016, 6, 22), "exit_date": date(2025, 1, 10),
         "inclusion_reason": "index_membership+liquidity_floor; delisted (bankruptcy)"},
        # --- recent entrants -------------------------------------------------------------
        {"ticker": "SYN-IPO-01", "entry_date": date(2025, 4, 7), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor; recent IPO"},
        {"ticker": "SYN-IPO-02", "entry_date": date(2026, 2, 2), "exit_date": None,
         "inclusion_reason": "index_membership+liquidity_floor; recent IPO"},
        # --- a name that fails the liquidity floor at the dataset's "as of" date --------
        {"ticker": "SYN-ILLIQUID-01", "entry_date": date(2020, 1, 6), "exit_date": None,
         "inclusion_reason": "index_membership only; below liquidity floor"},
    ]
    return pd.DataFrame(rows)


def sample_liquidity() -> pd.DataFrame:
    """Synthetic dollar-volume readings supporting the liquidity floor.

    Every ticker except ``SYN-ILLIQUID-01`` gets a reading comfortably above
    a plausible floor; ``SYN-ILLIQUID-01`` gets one below it, so a caller
    applying a liquidity floor on top of ``sample_membership()`` sees it
    dropped even though it is "in the index" per the membership table.
    """
    liquid_tickers = [
        "SYN-CORE-01", "SYN-CORE-02", "SYN-CORE-03", "SYN-CORE-04",
        "SYN-CORE-05", "SYN-CORE-06", "SYN-CORE-07", "SYN-CORE-08",
        "SYN-DELIST-01", "SYN-DELIST-02", "SYN-DELIST-03",
        "SYN-IPO-01", "SYN-IPO-02",
    ]
    rows = [
        {"ticker": t, "date": SAMPLE_DATASET_AS_OF, "dollar_volume": 25_000_000.0}
        for t in liquid_tickers
    ]
    rows.append({
        "ticker": "SYN-ILLIQUID-01",
        "date": SAMPLE_DATASET_AS_OF,
        "dollar_volume": 15_000.0,  # far below any reasonable floor
    })
    return pd.DataFrame(rows)


SAMPLE_LIQUIDITY_FLOOR = 1_000_000.0
