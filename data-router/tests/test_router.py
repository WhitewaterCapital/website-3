"""The router itself: vendor selection down a documented fallback chain,
quota enforcement, circuit-breaker checks, "a divergent fallback value is a
validation failure, not a silent substitution", and exactly-one write-through
per successful fetch."""

from datetime import date, datetime, timezone

import pytest

from router.adapters.base import Adapter, DataClass
from router.circuit import CircuitBreaker
from router.quota import QuotaManager
from router.router import DataRouter, NoVendorAvailableError, ValidationFailure
from router.schema import Bar
from router.store import InMemoryPointInTimeStore

_NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _bar(ticker: str, close: float, vendor: str, d: date = date(2024, 1, 2)) -> Bar:
    return Bar(
        ticker=ticker, open=close, high=close, low=close, close=close, volume=1000,
        observation_date=d, source_publication_time=_NOW, ingestion_time=_NOW,
        vendor=vendor, vendor_field_name="close",
    )


class FakeBarsAdapter(Adapter):
    """A minimal fake vendor for router tests: returns a fixed close price
    (or raises) for `get_bars`, and nothing else."""

    capabilities = frozenset({DataClass.BARS})

    def __init__(self, name: str, close: float | None = None, raises: bool = False):
        self.name = name
        self._close = close
        self._raises = raises
        self.calls = 0

    def get_bars(self, ticker: str, start: date, end: date):
        self.calls += 1
        if self._raises:
            raise RuntimeError(f"{self.name} is down")
        return [_bar(ticker, self._close, self.name)]


def _quota_unlimited(vendors: list[str]) -> QuotaManager:
    qm = QuotaManager()
    for v in vendors:
        qm.configure(v, per_minute=1000, per_day=1000)
    return qm


def _router(adapters: dict, chain: list[str], quota=None, circuits=None, store=None, **kwargs) -> DataRouter:
    # NOTE: deliberately `is None` everywhere here, not `or` -- an empty (but
    # very much real) `InMemoryPointInTimeStore` defines `__len__`, so a
    # freshly-created, not-yet-written-to store is falsy and `store or
    # InMemoryPointInTimeStore()` would silently swap it out from under a
    # caller that passed one in specifically to assert against it.
    return DataRouter(
        adapters=adapters,
        fallback_chains={DataClass.BARS: chain},
        quota=quota if quota is not None else _quota_unlimited(chain),
        circuits=circuits if circuits is not None else {v: CircuitBreaker(3, 60, 30) for v in chain},
        store=store if store is not None else InMemoryPointInTimeStore(),
        **kwargs,
    )


def test_fetch_uses_primary_vendor_when_healthy():
    primary = FakeBarsAdapter("primary", close=100.0)
    backup = FakeBarsAdapter("backup", close=100.0)
    r = _router({"primary": primary, "backup": backup}, ["primary", "backup"])

    result = r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert result.vendor == "primary"
    assert primary.calls == 1
    assert backup.calls == 0
    assert result.attempts[-1].outcome == "success"


def test_fetch_falls_back_when_primary_raises():
    primary = FakeBarsAdapter("primary", raises=True)
    backup = FakeBarsAdapter("backup", close=100.0)
    r = _router({"primary": primary, "backup": backup}, ["primary", "backup"])

    result = r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert result.vendor == "backup"
    assert any(a.outcome == "adapter_error" for a in result.attempts)


def test_fetch_skips_vendor_whose_circuit_is_open():
    primary = FakeBarsAdapter("primary", close=100.0)
    backup = FakeBarsAdapter("backup", close=100.0)
    tripped = CircuitBreaker(1, 60, 30)
    tripped.record_failure()  # trips immediately (threshold=1)
    assert tripped.allow_request() is False

    r = _router(
        {"primary": primary, "backup": backup},
        ["primary", "backup"],
        circuits={"primary": tripped, "backup": CircuitBreaker(3, 60, 30)},
    )
    result = r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert result.vendor == "backup"
    assert primary.calls == 0  # never even attempted
    assert any(a.outcome == "skipped_circuit_open" for a in result.attempts)


def test_fetch_skips_vendor_with_no_quota_left():
    primary = FakeBarsAdapter("primary", close=100.0)
    backup = FakeBarsAdapter("backup", close=100.0)
    qm = QuotaManager()
    qm.configure("primary", per_minute=1, per_day=1, burst_per_minute=1, burst_per_day=1)
    qm.configure("backup", per_minute=100, per_day=100)
    qm.consume_or_raise("primary")  # exhaust primary's only token up front

    r = _router({"primary": primary, "backup": backup}, ["primary", "backup"], quota=qm)
    result = r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert result.vendor == "backup"
    assert primary.calls == 0
    assert any(a.outcome == "skipped_no_quota" for a in result.attempts)


def test_fetch_raises_when_every_vendor_in_chain_fails():
    primary = FakeBarsAdapter("primary", raises=True)
    backup = FakeBarsAdapter("backup", raises=True)
    r = _router({"primary": primary, "backup": backup}, ["primary", "backup"])

    with pytest.raises(NoVendorAvailableError):
        r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})


def test_fallback_with_wildly_different_value_raises_validation_failure_not_silent_substitution():
    primary = FakeBarsAdapter("primary", raises=True)
    wild_backup = FakeBarsAdapter("backup", close=9999.0)  # wildly different
    r = _router({"primary": primary, "backup": wild_backup}, ["primary", "backup"])

    key = ("AAPL", "close")
    # Seed a recent primary-vendor reference value directly (simulating an
    # earlier successful primary call for the same key).
    from router.router import _ReferenceValue
    r._recent_values[key] = _ReferenceValue(value=100.0, vendor="primary", observed_at=_NOW)

    with pytest.raises(ValidationFailure):
        r.fetch(
            DataClass.BARS,
            {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)},
            comparison_key=key,
        )


def test_fallback_within_threshold_is_accepted():
    primary = FakeBarsAdapter("primary", raises=True)
    close_backup = FakeBarsAdapter("backup", close=101.0)  # 1% off a 100.0 reference
    r = _router({"primary": primary, "backup": close_backup}, ["primary", "backup"], divergence_threshold=0.05)

    key = ("AAPL", "close")
    from router.router import _ReferenceValue
    r._recent_values[key] = _ReferenceValue(value=100.0, vendor="primary", observed_at=_NOW)

    result = r.fetch(
        DataClass.BARS,
        {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)},
        comparison_key=key,
    )
    assert result.vendor == "backup"


def test_reasonableness_bound_rejects_out_of_band_value_with_no_prior_reference():
    primary = FakeBarsAdapter("primary", close=-5.0)  # a negative price is never sane
    r = _router({"primary": primary}, ["primary"])

    with pytest.raises(ValidationFailure):
        r.fetch(
            DataClass.BARS,
            {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)},
            reasonableness_bound=(0.0, 100000.0),
        )


def test_successful_fetch_results_in_exactly_one_write_call():
    store = InMemoryPointInTimeStore()
    primary = FakeBarsAdapter("primary", close=100.0)
    r = _router({"primary": primary}, ["primary"], store=store)

    r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert store.write_calls == 1
    assert len(store.records) == 1


def test_a_failed_fetch_writes_nothing():
    store = InMemoryPointInTimeStore()
    primary = FakeBarsAdapter("primary", raises=True)
    r = _router({"primary": primary}, ["primary"], store=store)

    with pytest.raises(NoVendorAvailableError):
        r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})

    assert store.write_calls == 0


def test_adapter_failure_records_a_circuit_breaker_failure():
    primary = FakeBarsAdapter("primary", raises=True)
    backup = FakeBarsAdapter("backup", close=100.0)
    primary_circuit = CircuitBreaker(1, 60, 30)
    r = _router(
        {"primary": primary, "backup": backup},
        ["primary", "backup"],
        circuits={"primary": primary_circuit, "backup": CircuitBreaker(3, 60, 30)},
    )
    r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})
    assert primary_circuit.allow_request() is False  # tripped by the failure


def test_unsupported_data_class_is_skipped_not_errored():
    class NewsOnlyAdapter(Adapter):
        name = "news-only"
        capabilities = frozenset({DataClass.NEWS})

    backup = FakeBarsAdapter("backup", close=100.0)
    r = _router({"news-only": NewsOnlyAdapter(), "backup": backup}, ["news-only", "backup"])
    result = r.fetch(DataClass.BARS, {"ticker": "AAPL", "start": date(2024, 1, 1), "end": date(2024, 1, 2)})
    assert result.vendor == "backup"


def test_local_file_adapter_end_to_end_through_the_router():
    """The one real adapter, wired all the way through the real router, with
    a real write-through store -- proves the whole stack composes."""
    from router.adapters.local_file import LocalFileAdapter

    adapter = LocalFileAdapter(clock=lambda: _NOW)
    store = InMemoryPointInTimeStore()

    fundamentals_router = DataRouter(
        adapters={"local-file-fixture": adapter},
        fallback_chains={DataClass.FUNDAMENTALS: ["local-file-fixture"]},
        quota=_quota_unlimited(["local-file-fixture"]),
        circuits={"local-file-fixture": CircuitBreaker(3, 60, 30)},
        store=store,
    )
    result = fundamentals_router.fetch(DataClass.FUNDAMENTALS, {"ticker": "AAPL"})
    assert result.vendor == "local-file-fixture"
    assert len(result.records) == 2
    assert store.write_calls == 1
