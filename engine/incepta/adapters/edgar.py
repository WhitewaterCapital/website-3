"""SEC EDGAR fundamentals adapter.

Pulls XBRL "company facts" and converts them into point-in-time `Fact` rows.

Compliance (verified 2026-08-04, https://www.sec.gov/os/accessing-edgar-data):
- No API key required.
- A descriptive `User-Agent` with a contact email is MANDATORY (else HTTP 403).
- Fair-access limit is 10 req/s; we self-limit (see config).

The point-in-time work happens in `_rows_from_company_facts`: for each
(taxonomy, concept, unit, period) we find the earliest `filed` date and flag that
row `is_first_reported=True`. Later filings of the same period are restatements
and are kept but flagged False, so a backtest can choose as-first-reported values.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

from .. import config
from ..features.concepts import tracked_concepts
from ..pit import Fact


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


class EdgarClient:
    name = "sec-edgar"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": config.sec_user_agent(),
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            }
        )
        self._last_request_ts = 0.0
        self._ticker_cik: Optional[dict[str, int]] = None

    # -- low-level HTTP with rate limiting + retries --------------------------
    def _get(self, url: str) -> requests.Response:
        for attempt in range(config.SEC_MAX_RETRIES):
            # self-throttle to stay under the SEC's 10 req/s
            gap = time.monotonic() - self._last_request_ts
            if gap < config.SEC_MIN_REQUEST_INTERVAL_S:
                time.sleep(config.SEC_MIN_REQUEST_INTERVAL_S - gap)
            self._last_request_ts = time.monotonic()

            resp = self._session.get(url, timeout=config.SEC_REQUEST_TIMEOUT_S)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:  # rate limited — back off and retry
                time.sleep(1.0 + attempt)
                continue
            if resp.status_code == 404:
                resp.raise_for_status()
            # transient server errors: retry
            if 500 <= resp.status_code < 600:
                time.sleep(0.5 + attempt)
                continue
            resp.raise_for_status()
        resp.raise_for_status()  # exhausted retries
        return resp  # unreachable, keeps type-checkers happy

    # -- ticker -> CIK --------------------------------------------------------
    def _load_ticker_map(self) -> dict[str, int]:
        if self._ticker_cik is not None:
            return self._ticker_cik

        cache = config.data_dir() / "company_tickers.json"
        raw: dict
        if cache.exists():
            raw = json.loads(cache.read_text())
        else:
            resp = self._get(config.SEC_COMPANY_TICKERS_URL)
            raw = resp.json()
            cache.write_text(json.dumps(raw))

        # File shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        mapping: dict[str, int] = {}
        for row in raw.values():
            mapping[str(row["ticker"]).upper()] = int(row["cik_str"])
        self._ticker_cik = mapping
        return mapping

    def resolve_cik(self, ticker: str) -> Optional[int]:
        return self._load_ticker_map().get(ticker.upper())

    # -- company metadata (name, SIC/sector) ----------------------------------
    def company_info(self, cik: int) -> dict:
        """Name + SIC industry code from the submissions endpoint. SIC is a free,
        point-in-time-safe sector proxy (GICS is licensed). Note: the SEC serves
        the *current* SIC; true historical reclassifications are not captured
        here — a known, documented limitation (dossier §13, classification bias).
        """
        url = f"{config.SEC_DATA_BASE}/submissions/CIK{cik:010d}.json"
        j = self._get(url).json()
        return {
            "name": j.get("name", ""),
            "sic": str(j.get("sic", "")),
            "sic_description": j.get("sicDescription", ""),
        }

    # -- company facts --------------------------------------------------------
    def _company_facts(self, cik: int) -> dict:
        url = config.SEC_COMPANY_FACTS_URL.format(cik10=f"{cik:010d}")
        return self._get(url).json()

    def fetch_facts(self, ticker: str) -> list[Fact]:
        cik = self.resolve_cik(ticker)
        if cik is None:
            raise ValueError(f"Unknown ticker (no CIK in SEC map): {ticker!r}")
        payload = self._company_facts(cik)
        return _rows_from_company_facts(ticker.upper(), cik, payload)


def _rows_from_company_facts(ticker: str, cik: int, payload: dict) -> list[Fact]:
    wanted = tracked_concepts()
    ingested = date.today()
    facts_section = payload.get("facts", {})

    # First pass: collect raw entries into a flat list of dicts.
    raw_rows: list[dict] = []
    for taxonomy, concepts in facts_section.items():
        for concept, body in concepts.items():
            if concept not in wanted:
                continue
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    end = _parse_date(e.get("end", ""))
                    filed = _parse_date(e.get("filed", ""))
                    if end is None or filed is None or e.get("val") is None:
                        continue
                    raw_rows.append(
                        {
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "period_start": _parse_date(e.get("start", "")),
                            "period_end": end,
                            "value": float(e["val"]),
                            "accn": e.get("accn", ""),
                            "form": e.get("form", ""),
                            "fiscal_year": e.get("fy"),
                            "fiscal_period": e.get("fp"),
                            "filed": filed,
                            "frame": e.get("frame"),
                        }
                    )

    # Second pass: mark the earliest-filed row per (concept, unit, period) as the
    # as-first-reported value. Ties (same filed date) → the first seen is kept.
    earliest: dict[tuple, date] = {}
    for r in raw_rows:
        key = (r["taxonomy"], r["concept"], r["unit"], r["period_start"], r["period_end"])
        if key not in earliest or r["filed"] < earliest[key]:
            earliest[key] = r["filed"]

    out: list[Fact] = []
    seen_first: set[tuple] = set()
    for r in raw_rows:
        key = (r["taxonomy"], r["concept"], r["unit"], r["period_start"], r["period_end"])
        is_first = r["filed"] == earliest[key] and key not in seen_first
        if is_first:
            seen_first.add(key)
        out.append(
            Fact(
                cik=cik,
                ticker=ticker,
                taxonomy=r["taxonomy"],
                concept=r["concept"],
                unit=r["unit"],
                period_start=r["period_start"],
                period_end=r["period_end"],
                value=r["value"],
                accn=r["accn"],
                form=r["form"],
                fiscal_year=r["fiscal_year"],
                fiscal_period=r["fiscal_period"],
                filed=r["filed"],
                frame=r["frame"],
                is_first_reported=is_first,
                ingested_at=ingested,
            )
        )
    return out
