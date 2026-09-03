"""Prove every data-class dataclass carries all five provenance fields and
cannot be constructed without them — the spec's own central guarantee.

Two ways a caller could try to skip provenance, both must fail:
  1. Omit the field entirely -> Python's own `TypeError` (structural check).
  2. Pass the field explicitly as `None` (or "" for the string fields) ->
     `MissingProvenanceError` from `ProvenanceMixin.__post_init__`.
"""

from datetime import date, datetime, timezone

import pytest

from router.schema import (
    Bar,
    CorporateAction,
    FundamentalFact,
    Holding,
    MacroObservation,
    MissingProvenanceError,
    NewsItem,
    ProvenanceMixin,
)

_OBS = date(2024, 1, 2)
_PUB = datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)
_ING = datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)


def _good_provenance() -> dict:
    return dict(
        observation_date=_OBS,
        source_publication_time=_PUB,
        ingestion_time=_ING,
        vendor="local-file-fixture",
        vendor_field_name="close",
    )


def test_bar_constructs_with_full_provenance():
    bar = Bar(
        ticker="AAPL", open=1, high=2, low=0.5, close=1.5, volume=100,
        **_good_provenance(),
    )
    assert bar.vendor == "local-file-fixture"
    assert bar.observation_date == _OBS


def test_bar_missing_provenance_field_raises_type_error_when_omitted():
    kwargs = _good_provenance()
    del kwargs["vendor"]
    with pytest.raises(TypeError):
        Bar(ticker="AAPL", open=1, high=2, low=0.5, close=1.5, volume=100, **kwargs)


@pytest.mark.parametrize("field_name", [
    "observation_date", "source_publication_time", "ingestion_time",
    "vendor", "vendor_field_name",
])
def test_bar_none_provenance_field_raises_missing_provenance_error(field_name):
    kwargs = _good_provenance()
    kwargs[field_name] = None
    with pytest.raises(MissingProvenanceError):
        Bar(ticker="AAPL", open=1, high=2, low=0.5, close=1.5, volume=100, **kwargs)


def test_bar_empty_string_vendor_raises_missing_provenance_error():
    kwargs = _good_provenance()
    kwargs["vendor"] = "   "  # whitespace-only, must be treated as missing
    with pytest.raises(MissingProvenanceError):
        Bar(ticker="AAPL", open=1, high=2, low=0.5, close=1.5, volume=100, **kwargs)


def test_every_data_class_is_a_provenance_mixin_subclass():
    for cls in (Bar, FundamentalFact, CorporateAction, Holding, NewsItem, MacroObservation):
        assert issubclass(cls, ProvenanceMixin)


def test_fundamental_fact_requires_provenance():
    with pytest.raises(TypeError):
        FundamentalFact(ticker="AAPL", concept="Revenues", unit="USD", value=1.0)
    fact = FundamentalFact(
        ticker="AAPL", concept="Revenues", unit="USD", value=1.0, **_good_provenance(),
    )
    assert fact.value == 1.0


def test_corporate_action_requires_provenance():
    with pytest.raises(TypeError):
        CorporateAction(ticker="AAPL", action_type="split")
    action = CorporateAction(ticker="AAPL", action_type="split", **_good_provenance())
    assert action.action_type == "split"


def test_holding_requires_provenance():
    with pytest.raises(TypeError):
        Holding(portfolio_id="p1", ticker="AAPL", quantity=1.0, market_value=1.0)
    holding = Holding(
        portfolio_id="p1", ticker="AAPL", quantity=1.0, market_value=1.0, **_good_provenance(),
    )
    assert holding.portfolio_id == "p1"


def test_news_item_requires_provenance():
    with pytest.raises(TypeError):
        NewsItem(headline="h", url="u")
    item = NewsItem(headline="h", url="u", **_good_provenance())
    assert item.headline == "h"


def test_macro_observation_requires_provenance():
    with pytest.raises(TypeError):
        MacroObservation(series_id="CPIAUCSL", value=1.0, unit="index")
    obs = MacroObservation(series_id="CPIAUCSL", value=1.0, unit="index", **_good_provenance())
    assert obs.series_id == "CPIAUCSL"


def test_records_are_frozen():
    bar = Bar(ticker="AAPL", open=1, high=2, low=0.5, close=1.5, volume=100, **_good_provenance())
    with pytest.raises(Exception):
        bar.close = 999.0  # type: ignore[misc]
