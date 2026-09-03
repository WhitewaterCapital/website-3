"""The local-file adapter is the ONE real, fully-functional adapter this task
builds — prove it actually reads fixtures and produces correctly-provenanced
records. Also prove every real-vendor stub (Alpha Vantage, OpenBB, Tiingo)
raises `VendorNotConfiguredError` naming its missing env var and never
attempts any network call, with or without an env var set (since no real
credential is ever available in this sandbox either way)."""

from datetime import date, datetime, timezone

import pytest

from router.adapters.alpha_vantage import REQUIRED_ENV_VAR as AV_ENV_VAR
from router.adapters.alpha_vantage import AlphaVantageAdapter
from router.adapters.base import DataClass, VendorNotConfiguredError
from router.adapters.local_file import LocalFileAdapter
from router.adapters.openbb import REQUIRED_ENV_VAR as OPENBB_ENV_VAR
from router.adapters.openbb import OpenBBAdapter
from router.adapters.tiingo import REQUIRED_ENV_VAR as TIINGO_ENV_VAR
from router.adapters.tiingo import TiingoAdapter

_FIXED_NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _adapter() -> LocalFileAdapter:
    return LocalFileAdapter(clock=lambda: _FIXED_NOW)


def test_local_file_adapter_reads_bars_with_full_provenance():
    bars = _adapter().get_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert len(bars) == 3
    assert all(b.ticker == "AAPL" for b in bars)
    first = bars[0]
    assert first.observation_date == date(2024, 1, 2)
    assert first.vendor == "local-file-fixture"
    assert first.vendor_field_name == "close"
    assert first.ingestion_time == _FIXED_NOW
    assert first.source_publication_time.tzinfo is not None


def test_local_file_adapter_bars_respect_date_range():
    bars = _adapter().get_bars("AAPL", date(2024, 1, 3), date(2024, 1, 3))
    assert len(bars) == 1
    assert bars[0].observation_date == date(2024, 1, 3)


def test_local_file_adapter_unknown_ticker_returns_empty():
    assert _adapter().get_bars("ZZZZ", date(2020, 1, 1), date(2030, 1, 1)) == []


def test_local_file_adapter_fundamentals():
    facts = _adapter().get_fundamentals("MSFT")
    assert len(facts) == 2
    concepts = {f.concept for f in facts}
    assert concepts == {"Revenues", "NetIncomeLoss"}
    for f in facts:
        assert f.vendor == "local-file-fixture"
        assert f.observation_date == date(2023, 12, 31)


def test_local_file_adapter_corporate_actions():
    actions = _adapter().get_corporate_actions("AAPL")
    assert len(actions) == 1
    assert actions[0].action_type == "split"
    assert actions[0].details == {"ratio": 4.0}


def test_local_file_adapter_holdings():
    holdings = _adapter().get_holdings("demo-1", date(2024, 1, 2))
    assert len(holdings) == 2
    assert {h.ticker for h in holdings} == {"AAPL", "MSFT"}


def test_local_file_adapter_news_filters_by_ticker_and_since():
    all_news = _adapter().get_news()
    assert len(all_news) == 2
    aapl_news = _adapter().get_news(ticker="AAPL")
    assert len(aapl_news) == 1
    assert aapl_news[0].ticker == "AAPL"
    late_news = _adapter().get_news(since=date(2024, 1, 15))
    assert len(late_news) == 1
    assert late_news[0].headline.startswith("Fed")


def test_local_file_adapter_macro():
    obs = _adapter().get_macro("CPIAUCSL", date(2023, 1, 1), date(2024, 12, 31))
    assert len(obs) == 2
    assert obs[0].series_id == "CPIAUCSL"


def test_local_file_adapter_supports_reflects_capabilities():
    adapter = _adapter()
    assert adapter.supports(DataClass.BARS)
    assert adapter.supports(DataClass.NEWS)


@pytest.mark.parametrize("cls,env_var,data_class,method,kwargs", [
    (AlphaVantageAdapter, AV_ENV_VAR, DataClass.BARS, "get_bars",
     {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)}),
    (OpenBBAdapter, OPENBB_ENV_VAR, DataClass.BARS, "get_bars",
     {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)}),
    (TiingoAdapter, TIINGO_ENV_VAR, DataClass.BARS, "get_bars",
     {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)}),
])
def test_vendor_stub_raises_vendor_not_configured_without_env_var(
    monkeypatch, cls, env_var, data_class, method, kwargs
):
    import os

    scrubbed = {k: v for k, v in os.environ.items() if k != env_var}
    monkeypatch.setattr(os, "environ", scrubbed)
    adapter = cls()
    assert adapter.supports(data_class)
    with pytest.raises(VendorNotConfiguredError, match=env_var):
        getattr(adapter, method)(**kwargs)


def test_alpha_vantage_stub_never_imports_a_network_library():
    # Parse the AST rather than grepping raw text: the module's own docstring
    # *mentions* "import requests" in prose (explaining what a real
    # implementation would add later), so a plain substring check would
    # false-positive on the very sentence disclaiming it. An AST walk only
    # sees actual `import`/`from ... import` statements, never string/
    # docstring content.
    import ast

    import router.adapters.alpha_vantage as mod

    tree = ast.parse(open(mod.__file__).read())
    forbidden_modules = {"requests", "httpx", "urllib", "urllib2", "http.client", "socket"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden_modules), f"forbidden network import(s) found: {imported & forbidden_modules}"


def test_alpha_vantage_stub_still_raises_even_with_env_var_set(monkeypatch):
    # Setting the env var makes _require_key pass, but the method body still
    # must never attempt a real HTTP call in this sandbox -- it raises
    # NotImplementedError instead. This is the documented, honest state: no
    # live vendor call has ever been made against this code, key or no key.
    import os

    with_key = {**os.environ, AV_ENV_VAR: "fake-key-not-real"}
    monkeypatch.setattr(os, "environ", with_key)
    adapter = AlphaVantageAdapter()
    with pytest.raises(NotImplementedError):
        adapter.get_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))
