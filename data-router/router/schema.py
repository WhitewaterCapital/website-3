"""One internal schema per data class, per the router spec.

The spec's own words: "Every field carries value, observation date, source
publication time, ingestion time, vendor and vendor field name." We read that
as five *provenance* fields (the payload — "value" — is whatever the concrete
data class carries: an OHLCV bar, a fundamental fact, a corporate action, a
holding, a news item, a macro observation) that must ride along with every
single record the router hands back to a model. A model that receives one of
these dataclasses can always answer "where did this number come from and when
did we learn it" without a second lookup.

`ProvenanceMixin` is the structural guarantee: it is a frozen dataclass with
no default values on any of its five fields, and every concrete data class
below inherits from it. Two independent enforcement mechanisms are stacked
here on purpose:

1. **Structural** — `@dataclass` with no defaults means Python itself raises
   `TypeError` if a caller omits a provenance field. This is the primary,
   "impossible to forget" guarantee and needs no code to keep working.
2. **Explicit validation** — `__post_init__` additionally rejects `None` (or
   an empty string for the two string fields), because a caller can always
   pass `observation_date=None` explicitly and satisfy Python's structural
   check while still producing a useless, unprovenanced record.

All dataclasses use `kw_only=True` so field order across the mixin and each
subclass never has to fight Python's "no default before non-default" rule —
every field is required unless it is explicitly given a default, independent
of declaration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


class MissingProvenanceError(ValueError):
    """Raised when a data-class record is constructed with a null (as opposed
    to simply omitted — Python's own TypeError already blocks that) provenance
    field. Kept as a distinct exception type so callers can catch it
    specifically rather than a bare ValueError."""


_PROVENANCE_FIELDS = (
    "observation_date",
    "source_publication_time",
    "ingestion_time",
    "vendor",
    "vendor_field_name",
)


@dataclass(frozen=True, kw_only=True)
class ProvenanceMixin:
    """The five fields every record the router emits must carry.

    - observation_date:        the date the observed fact *pertains to*
                                (a bar's trading date, a fact's period end,
                                an action's effective date, ...).
    - source_publication_time: when the vendor says the value became public
                                (a filing timestamp, a bar's close-and-publish
                                time, a news wire timestamp, ...).
    - ingestion_time:           when *this router* pulled the value in. Never
                                backdated — it is a receipt, not a fact about
                                the world.
    - vendor:                   internal vendor id (e.g. "local-file-fixture",
                                "alpha-vantage"). Never surfaced to a model as
                                a "which vendor should I trust" decision —
                                that decision lives in the router, not
                                downstream — but it must be recorded so a
                                fallback/divergence audit is always possible.
    - vendor_field_name:         the vendor's own name for this field (e.g.
                                Alpha Vantage's "4. close"), so a schema
                                mapping bug is traceable back to the exact
                                source field.
    """

    observation_date: date
    source_publication_time: datetime
    ingestion_time: datetime
    vendor: str
    vendor_field_name: str

    def __post_init__(self) -> None:
        missing = []
        for name in _PROVENANCE_FIELDS:
            value = getattr(self, name)
            if value is None:
                missing.append(name)
            elif isinstance(value, str) and not value.strip():
                missing.append(name)
        if missing:
            raise MissingProvenanceError(
                f"{type(self).__name__} is missing required provenance "
                f"field(s): {', '.join(missing)}. Every record the data "
                f"router emits must carry all five provenance fields — see "
                f"router.schema.ProvenanceMixin."
            )


@dataclass(frozen=True, kw_only=True)
class Bar(ProvenanceMixin):
    """One OHLCV bar. `observation_date` is the trading date the bar covers."""

    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, kw_only=True)
class FundamentalFact(ProvenanceMixin):
    """One reported fundamental data point (revenue, EPS, total assets, ...).

    Mirrors the shape of `incepta.pit.Fact` (engine/incepta/pit.py) but scoped
    to what the router itself needs to move the value around safely; the
    engine's PIT store remains the system of record for full XBRL detail.
    `observation_date` is the fiscal period end the fact describes.
    """

    ticker: str
    concept: str  # e.g. "Revenues", "EPS_Diluted"
    unit: str  # e.g. "USD", "USD/shares"
    value: float
    period_start: Optional[date] = None


@dataclass(frozen=True, kw_only=True)
class CorporateAction(ProvenanceMixin):
    """A split, dividend, merger, spinoff, or delisting event.

    `observation_date` is the action's effective date. `details` carries
    action-specific fields (e.g. {"ratio": 2.0} for a split, {"amount": 0.24}
    for a cash dividend) since the shape legitimately varies by action type.
    """

    ticker: str
    action_type: str  # "split" | "dividend" | "merger" | "spinoff" | "delisting"
    details: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Holding(ProvenanceMixin):
    """One position in a portfolio as of a date. `observation_date` is the
    as-of date of the holding snapshot."""

    portfolio_id: str
    ticker: str
    quantity: float
    market_value: float


@dataclass(frozen=True, kw_only=True)
class NewsItem(ProvenanceMixin):
    """A news headline/story. `observation_date` is the story's publish date;
    `ticker` is None for market-wide (non-company-specific) news."""

    headline: str
    url: str
    ticker: Optional[str] = None
    sentiment: Optional[float] = None


@dataclass(frozen=True, kw_only=True)
class MacroObservation(ProvenanceMixin):
    """One macro time-series observation (CPI, Fed funds rate, unemployment,
    ...). `observation_date` is the period the observation describes, which
    for many macro series (e.g. monthly CPI) predates when it was actually
    released — that gap is exactly why `source_publication_time` matters:
    macro data has its own, often-late, look-ahead trap."""

    series_id: str  # e.g. "CPIAUCSL"
    value: float
    unit: str
