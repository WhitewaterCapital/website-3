"""Local DuckDB implementation of the feature store.

DuckDB is a single-file, columnar, zero-server database — ideal for a research
feature store and fast backtests. The same `FeatureStore` interface will later be
implemented against Supabase Postgres for the website's serving layer; nothing
that consumes the store needs to change.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb

from .. import config
from ..features.concepts import STANDARD_CONCEPTS
from ..pit import Fact, PriceBar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    cik               INTEGER   NOT NULL,
    ticker            VARCHAR   NOT NULL,
    taxonomy          VARCHAR   NOT NULL,
    concept           VARCHAR   NOT NULL,
    unit              VARCHAR   NOT NULL,
    period_start      DATE,
    period_end        DATE      NOT NULL,
    value             DOUBLE    NOT NULL,
    accn              VARCHAR   NOT NULL,
    form              VARCHAR,
    fiscal_year       INTEGER,
    fiscal_period     VARCHAR,
    filed             DATE      NOT NULL,
    frame             VARCHAR,
    is_first_reported BOOLEAN   NOT NULL,
    ingested_at       DATE      NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    ticker      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE  NOT NULL,
    volume      DOUBLE,
    source      VARCHAR,
    adjusted    BOOLEAN,
    ingested_at DATE,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS companies (
    cik             INTEGER PRIMARY KEY,
    ticker          VARCHAR,
    name            VARCHAR,
    sic             VARCHAR,
    sic_description VARCHAR,
    ingested_at     DATE
);
"""


class DuckDBStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or str(config.duckdb_path())
        self._con = duckdb.connect(self._path)
        self._con.execute(_SCHEMA)

    # -- writes ---------------------------------------------------------------
    def upsert_facts(self, facts: list[Fact]) -> int:
        if not facts:
            return 0
        # Idempotent per company: replace this CIK's rows, then bulk-insert.
        cik = facts[0].cik
        self._con.execute("DELETE FROM facts WHERE cik = ?", [cik])
        rows = [
            (
                f.cik, f.ticker, f.taxonomy, f.concept, f.unit,
                f.period_start, f.period_end, f.value, f.accn, f.form,
                f.fiscal_year, f.fiscal_period, f.filed, f.frame,
                f.is_first_reported, f.ingested_at,
            )
            for f in facts
        ]
        self._con.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        return len(rows)

    # -- point-in-time reads --------------------------------------------------
    def facts_asof(
        self, ticker: str, asof: date, first_reported_only: bool = True
    ) -> list[dict]:
        sql = """
            SELECT concept, unit, period_start, period_end, value, form,
                   fiscal_year, fiscal_period, filed, is_first_reported
            FROM facts
            WHERE ticker = ? AND filed <= ?
        """
        params: list = [ticker.upper(), asof]
        if first_reported_only:
            sql += " AND is_first_reported = TRUE"
        sql += " ORDER BY concept, period_end, filed"
        cur = self._con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def latest_standardized_asof(self, ticker: str, asof: date) -> dict:
        """For each standardized field, the value from the most recent period that
        was public on/before `asof`, using as-first-reported values."""
        visible = self.facts_asof(ticker, asof, first_reported_only=True)
        by_concept: dict[str, list[dict]] = {}
        for row in visible:
            by_concept.setdefault(row["concept"], []).append(row)

        out: dict[str, dict] = {}
        for field, candidates in STANDARD_CONCEPTS.items():
            for concept in candidates:  # priority order
                rows = by_concept.get(concept)
                if not rows:
                    continue
                # most recent completed period, tie-broken by latest filing
                best = max(rows, key=lambda r: (r["period_end"], r["filed"]))
                out[field] = {
                    "value": best["value"],
                    "concept": concept,
                    "unit": best["unit"],
                    "period_end": best["period_end"],
                    "form": best["form"],
                    "filed": best["filed"],
                }
                break
        return out

    def standardized_series_asof(
        self, ticker: str, asof: date, annual_only: bool = True
    ) -> dict:
        """For each standardized field, the full time series (as-first-reported,
        public on/before `asof`) as a list of {period_end, value, form}, oldest
        first. Enables YoY growth, accruals, issuance — all point-in-time.
        """
        visible = self.facts_asof(ticker, asof, first_reported_only=True)
        by_concept: dict[str, list[dict]] = {}
        for row in visible:
            if annual_only and (row["form"] or "") not in ("10-K", "10-K/A", "20-F"):
                continue
            by_concept.setdefault(row["concept"], []).append(row)

        out: dict[str, list[dict]] = {}
        for field, candidates in STANDARD_CONCEPTS.items():
            for concept in candidates:
                rows = by_concept.get(concept)
                if not rows:
                    continue
                # one value per period_end (first-reported already), oldest first
                dedup: dict = {}
                for r in rows:
                    dedup[r["period_end"]] = r
                series = [
                    {"period_end": pe, "value": dedup[pe]["value"], "form": dedup[pe]["form"]}
                    for pe in sorted(dedup)
                ]
                out[field] = series
                break
        return out

    # -- prices ---------------------------------------------------------------
    def upsert_prices(self, bars: list[PriceBar]) -> int:
        if not bars:
            return 0
        ticker = bars[0].ticker
        self._con.execute("DELETE FROM prices WHERE ticker = ?", [ticker])
        rows = [
            (b.ticker, b.date, b.open, b.high, b.low, b.close, b.volume,
             b.source, b.adjusted, b.ingested_at)
            for b in bars
        ]
        self._con.executemany(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?)", rows
        )
        return len(rows)

    def prices(
        self, ticker: str, start=None, end=None
    ) -> list[dict]:
        """Daily bars ordered by date. `end` acts as the point-in-time cutoff:
        a bar dated D is knowable only after D's close, so `date <= end`."""
        sql = "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ?"
        params: list = [ticker.upper()]
        if start is not None:
            sql += " AND date >= ?"
            params.append(start)
        if end is not None:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date"
        cur = self._con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def latest_price_asof(self, ticker: str, asof) -> Optional[dict]:
        cur = self._con.execute(
            "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? "
            "ORDER BY date DESC LIMIT 1",
            [ticker.upper(), asof],
        )
        row = cur.fetchone()
        return {"date": row[0], "close": row[1]} if row else None

    # -- companies (sector etc.) ---------------------------------------------
    def upsert_company(
        self, cik: int, ticker: str, name: str, sic: str, sic_description: str
    ) -> None:
        from datetime import date as _date
        self._con.execute("DELETE FROM companies WHERE cik = ?", [cik])
        self._con.execute(
            "INSERT INTO companies VALUES (?,?,?,?,?,?)",
            [cik, ticker.upper(), name, sic, sic_description, _date.today()],
        )

    def company(self, ticker: str) -> Optional[dict]:
        cur = self._con.execute(
            "SELECT cik, ticker, name, sic, sic_description FROM companies "
            "WHERE ticker = ? LIMIT 1",
            [ticker.upper()],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    # -- misc -----------------------------------------------------------------
    def summary(self, ticker: str) -> dict:
        cur = self._con.execute(
            """
            SELECT COUNT(*), MIN(period_end), MAX(period_end),
                   MIN(filed), MAX(filed),
                   SUM(CASE WHEN is_first_reported THEN 1 ELSE 0 END)
            FROM facts WHERE ticker = ?
            """,
            [ticker.upper()],
        )
        n, min_pe, max_pe, min_f, max_f, first_n = cur.fetchone()
        return {
            "rows": n,
            "period_end_min": min_pe,
            "period_end_max": max_pe,
            "filed_min": min_f,
            "filed_max": max_f,
            "first_reported_rows": first_n,
        }

    def close(self) -> None:
        self._con.close()
