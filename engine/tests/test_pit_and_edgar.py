"""The most important tests in the repo: prove the store cannot leak the future
and that as-first-reported selection is correct."""

from datetime import date

from incepta.adapters.edgar import _rows_from_company_facts
from incepta.pit import Fact
from incepta.store.duckdb_store import DuckDBStore


def _fact(concept, period_end, val, filed, accn, first, form="10-K"):
    return Fact(
        cik=1, ticker="TST", taxonomy="us-gaap", concept=concept, unit="USD",
        period_start=None, period_end=period_end, value=val, accn=accn, form=form,
        fiscal_year=period_end.year, fiscal_period="FY", filed=filed, frame=None,
        is_first_reported=first, ingested_at=date(2026, 1, 1),
    )


def test_asof_never_returns_future_filings():
    store = DuckDBStore(path=":memory:")
    facts = [
        # FY2020 revenue, first reported 2021-02-01, restated 2021-08-01
        _fact("Revenues", date(2020, 12, 31), 100.0, date(2021, 2, 1), "a1", True),
        _fact("Revenues", date(2020, 12, 31), 105.0, date(2021, 8, 1), "a2", False),
        # FY2021 revenue, filed 2022-02-01 — must be INVISIBLE as of 2021-06-01
        _fact("Revenues", date(2021, 12, 31), 130.0, date(2022, 2, 1), "a3", True),
    ]
    store.upsert_facts(facts)

    asof = date(2021, 6, 1)
    rows = store.facts_asof("TST", asof, first_reported_only=True)
    # only the FY2020 first-reported row is knowable on 2021-06-01
    assert len(rows) == 1
    assert rows[0]["value"] == 100.0            # first-reported, not the 105 restatement
    assert all(r["filed"] <= asof for r in rows)  # NOTHING filed after asof
    store.close()


def test_standardized_uses_first_reported_value():
    store = DuckDBStore(path=":memory:")
    store.upsert_facts([
        _fact("Revenues", date(2020, 12, 31), 100.0, date(2021, 2, 1), "a1", True),
        _fact("Revenues", date(2020, 12, 31), 105.0, date(2021, 8, 1), "a2", False),
    ])
    # after the restatement date, still return as-first-reported (100), not 105
    std = store.latest_standardized_asof("TST", date(2022, 1, 1))
    assert std["revenue"]["value"] == 100.0
    store.close()


def test_edgar_first_reported_flag():
    # two filings of the same period; the earlier `filed` must be first-reported
    payload = {
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"end": "2020-12-31", "val": 105, "accn": "a2", "form": "10-K/A", "filed": "2021-08-01"},
            {"end": "2020-12-31", "val": 100, "accn": "a1", "form": "10-K", "filed": "2021-02-01"},
        ]}}}}
    }
    rows = _rows_from_company_facts("TST", 1, payload)
    first = [r for r in rows if r.is_first_reported]
    assert len(first) == 1
    assert first[0].value == 100 and first[0].filed == date(2021, 2, 1)
