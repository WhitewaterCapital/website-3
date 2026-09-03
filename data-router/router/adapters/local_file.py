"""LocalFileAdapter — a stand-in vendor for testing the router's plumbing.

This is the ONE real, fully-functional adapter in this task. It reads
synthetic JSON fixtures from `router/adapters/fixtures/` and returns them as
fully provenance-stamped schema records. It exists purely to exercise the
router (quota, circuit breaker, fallback/divergence validation, write-through)
end to end without any network access — it is not, and is never claimed to
be, a real market-data vendor. Every value in `fixtures/*.json` is made up.

`clock` is injectable (defaults to `datetime.now(timezone.utc)`) purely so
tests can assert an exact `ingestion_time` instead of a fuzzy "recent enough"
check.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..schema import (
    Bar,
    CorporateAction,
    FundamentalFact,
    Holding,
    MacroObservation,
    NewsItem,
)
from .base import Adapter, DataClass

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_dt(s: str) -> datetime:
    # fixtures use a trailing "Z"; fromisoformat wants "+00:00" pre-3.11 quirks
    # aside, do the substitution defensively either way.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class LocalFileAdapter(Adapter):
    """Reads bars/fundamentals/corporate actions/holdings/news/macro from
    local JSON fixtures. Stand-in vendor for router plumbing tests only."""

    name = "local-file-fixture"
    capabilities = frozenset(
        {
            DataClass.BARS,
            DataClass.FUNDAMENTALS,
            DataClass.CORPORATE_ACTIONS,
            DataClass.HOLDINGS,
            DataClass.NEWS,
            DataClass.MACRO,
        }
    )

    def __init__(
        self,
        fixtures_dir: Path = FIXTURES_DIR,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._dir = fixtures_dir
        self._clock = clock

    def _load(self, filename: str) -> list[dict]:
        path = self._dir / filename
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def get_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        now = self._clock()
        out: list[Bar] = []
        for row in self._load("bars.json"):
            if row["ticker"] != ticker:
                continue
            d = _parse_date(row["date"])
            if not (start <= d <= end):
                continue
            out.append(
                Bar(
                    ticker=row["ticker"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    observation_date=d,
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name="close",
                )
            )
        return out

    def get_fundamentals(self, ticker: str) -> list[FundamentalFact]:
        now = self._clock()
        out: list[FundamentalFact] = []
        for row in self._load("fundamentals.json"):
            if row["ticker"] != ticker:
                continue
            out.append(
                FundamentalFact(
                    ticker=row["ticker"],
                    concept=row["concept"],
                    unit=row["unit"],
                    value=row["value"],
                    period_start=_parse_date(row["period_start"]) if row.get("period_start") else None,
                    observation_date=_parse_date(row["period_end"]),
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name=row["concept"],
                )
            )
        return out

    def get_corporate_actions(self, ticker: str) -> list[CorporateAction]:
        now = self._clock()
        out: list[CorporateAction] = []
        for row in self._load("corporate_actions.json"):
            if row["ticker"] != ticker:
                continue
            out.append(
                CorporateAction(
                    ticker=row["ticker"],
                    action_type=row["action_type"],
                    details=row.get("details", {}),
                    observation_date=_parse_date(row["effective_date"]),
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name=row["action_type"],
                )
            )
        return out

    def get_holdings(self, portfolio_id: str, as_of: date) -> list[Holding]:
        now = self._clock()
        out: list[Holding] = []
        for row in self._load("holdings.json"):
            if row["portfolio_id"] != portfolio_id:
                continue
            d = _parse_date(row["as_of_date"])
            if d != as_of:
                continue
            out.append(
                Holding(
                    portfolio_id=row["portfolio_id"],
                    ticker=row["ticker"],
                    quantity=row["quantity"],
                    market_value=row["market_value"],
                    observation_date=d,
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name="market_value",
                )
            )
        return out

    def get_news(self, ticker: Optional[str] = None, since: Optional[date] = None) -> list[NewsItem]:
        now = self._clock()
        out: list[NewsItem] = []
        for row in self._load("news.json"):
            if ticker is not None and row.get("ticker") != ticker:
                continue
            d = _parse_date(row["publish_date"])
            if since is not None and d < since:
                continue
            out.append(
                NewsItem(
                    ticker=row.get("ticker"),
                    headline=row["headline"],
                    url=row["url"],
                    sentiment=row.get("sentiment"),
                    observation_date=d,
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name="headline",
                )
            )
        return out

    def get_macro(self, series_id: str, start: date, end: date) -> list[MacroObservation]:
        now = self._clock()
        out: list[MacroObservation] = []
        for row in self._load("macro.json"):
            if row["series_id"] != series_id:
                continue
            d = _parse_date(row["period_date"])
            if not (start <= d <= end):
                continue
            out.append(
                MacroObservation(
                    series_id=row["series_id"],
                    value=row["value"],
                    unit=row["unit"],
                    observation_date=d,
                    source_publication_time=_parse_dt(row["source_publication_time"]),
                    ingestion_time=now,
                    vendor=self.name,
                    vendor_field_name=row["series_id"],
                )
            )
        return out
