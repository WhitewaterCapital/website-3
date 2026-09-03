"""The data router itself: the one internal service every model calls.

A model never holds a vendor key and never knows a vendor's name — it calls
`DataRouter.fetch(data_class, method_kwargs)` and gets back a list of
`router.schema` records. Everything vendor-specific happens inside `fetch`:

1. Walk the documented fallback chain for the data class, in priority order.
2. Skip any vendor whose circuit breaker has it pulled out of rotation.
3. Skip any vendor with no quota left (checked, not just attempted).
4. Call the adapter; a raised exception counts as a circuit-breaker failure
   and moves on to the next vendor in the chain.
5. **Validate, don't silently substitute.** If this vendor is a fallback (not
   the chain's first vendor) and a recent value from a higher-priority vendor
   is on record for the same `comparison_key`, a materially different value
   (relative difference beyond `divergence_threshold`) raises
   `ValidationFailure` instead of being returned. An optional
   `reasonableness_bound=(lo, hi)` catches an out-of-band value even with no
   prior reference at all (useful for the very first call for a key).
6. Write through to the point-in-time store — exactly one `store.write(...)`
   call per successful `fetch`, carrying every record that call produced.

Request-priority arbitration under quota contention (e.g. "a chaos-engine
pull must never queue behind a bulk fundamentals backfill") is provided by
`router.quota.PriorityRequestQueue` and is intentionally a separate concern
from `DataRouter` here: a deployment with many concurrent callers puts a
dispatcher in front of `DataRouter.fetch` that pops requests from that queue
in priority order and calls `fetch` once per request. `DataRouter` itself
stays a synchronous, single-request-at-a-time function so its vendor-
selection and validation logic is simple to test in isolation (see
`router/quota.py`'s own priority-ordering test for that half of the story).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .adapters.base import Adapter, DataClass, METHOD_FOR_DATA_CLASS
from .circuit import CircuitBreaker
from .quota import QuotaManager
from .store import PointInTimeStore


class ValidationFailure(RuntimeError):
    """Raised when a fallback vendor's value diverges materially from the
    reference value (a recent primary-vendor value, or a configured
    reasonableness bound) for the same comparison key. This is the spec's
    named rule made concrete: a divergent fallback value is a validation
    failure, never a silent substitution."""


class NoVendorAvailableError(RuntimeError):
    """Raised when every vendor in a data class's fallback chain is either
    unconfigured for that data class, circuit-broken, out of quota, or
    raised an error."""


# Extracts a single comparable scalar from a list of records for divergence
# checking. Corporate actions and news have no natural single scalar to
# compare across vendors, so they are simply not divergence-checked (`None`
# extractor result skips the check entirely — see `DataRouter.fetch`).
_DEFAULT_EXTRACTORS: dict[DataClass, Callable[[list], Optional[float]]] = {
    DataClass.BARS: lambda records: records[-1].close if records else None,
    DataClass.FUNDAMENTALS: lambda records: records[-1].value if records else None,
    DataClass.HOLDINGS: lambda records: records[-1].market_value if records else None,
    DataClass.MACRO: lambda records: records[-1].value if records else None,
    DataClass.CORPORATE_ACTIONS: lambda records: None,
    DataClass.NEWS: lambda records: None,
}


@dataclass
class _ReferenceValue:
    value: float
    vendor: str
    observed_at: datetime


@dataclass
class FetchAttempt:
    """One line of the router's decision log for a single `fetch` call —
    useful for tests and for debugging "why did the router pick vendor X"."""

    vendor: str
    outcome: str  # "success" | "skipped_circuit_open" | "skipped_no_quota" | "adapter_error" | "validation_failure"
    detail: str = ""


@dataclass
class FetchResult:
    records: list
    vendor: str
    attempts: list[FetchAttempt] = field(default_factory=list)


class DataRouter:
    def __init__(
        self,
        adapters: dict[str, Adapter],
        fallback_chains: dict[DataClass, list[str]],
        quota: QuotaManager,
        circuits: dict[str, CircuitBreaker],
        store: PointInTimeStore,
        divergence_threshold: float = 0.05,
        extractors: Optional[dict[DataClass, Callable[[list], Optional[float]]]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """
        adapters:            vendor name -> Adapter instance.
        fallback_chains:     data class -> ordered list of vendor names,
                             highest priority (primary) first. This is the
                             "documented priority/fallback chain" the spec
                             asks for — documented by being an explicit,
                             inspectable list rather than implicit code.
        quota:               a configured QuotaManager (see quota.py) —
                             every vendor referenced in fallback_chains must
                             be `.configure()`-ed there.
        circuits:            vendor name -> CircuitBreaker.
        store:               write-through target (see store.py).
        divergence_threshold: relative difference (0.05 = 5%) above which a
                             fallback value is rejected rather than returned.
        extractors:          override the default per-data-class "which
                             field do we compare across vendors" functions.
        """
        self._adapters = adapters
        self._fallback_chains = fallback_chains
        self._quota = quota
        self._circuits = circuits
        self._store = store
        self._divergence_threshold = divergence_threshold
        self._extractors = {**_DEFAULT_EXTRACTORS, **(extractors or {})}
        self._clock = clock
        self._recent_values: dict[tuple, _ReferenceValue] = {}

    def _extract(self, data_class: DataClass, records: list) -> Optional[float]:
        extractor = self._extractors.get(data_class)
        if extractor is None:
            return None
        return extractor(records)

    def fetch(
        self,
        data_class: DataClass,
        method_kwargs: dict,
        *,
        comparison_key: Optional[tuple] = None,
        reasonableness_bound: Optional[tuple] = None,
        quota_cost: float = 1.0,
    ) -> FetchResult:
        chain = self._fallback_chains.get(data_class, [])
        if not chain:
            raise NoVendorAvailableError(f"no fallback chain configured for {data_class}")

        method_name = METHOD_FOR_DATA_CLASS[data_class]
        attempts: list[FetchAttempt] = []

        for position, vendor in enumerate(chain):
            is_primary = position == 0
            adapter = self._adapters.get(vendor)
            if adapter is None or not adapter.supports(data_class):
                attempts.append(FetchAttempt(vendor, "skipped_unsupported"))
                continue

            circuit = self._circuits.get(vendor)
            if circuit is not None and not circuit.allow_request():
                attempts.append(FetchAttempt(vendor, "skipped_circuit_open"))
                continue

            if not self._quota.try_consume(vendor, quota_cost):
                attempts.append(FetchAttempt(vendor, "skipped_no_quota"))
                continue

            try:
                method = getattr(adapter, method_name)
                records = method(**method_kwargs)
            except Exception as exc:  # noqa: BLE001 — deliberately broad: any
                # adapter failure (network error, parse error, vendor 5xx,
                # ...) is a circuit-breaker failure and a reason to fail over.
                if circuit is not None:
                    circuit.record_failure()
                attempts.append(FetchAttempt(vendor, "adapter_error", str(exc)))
                continue

            if circuit is not None:
                circuit.record_success()

            value = self._extract(data_class, records)

            if reasonableness_bound is not None and value is not None:
                lo, hi = reasonableness_bound
                if not (lo <= value <= hi):
                    attempts.append(
                        FetchAttempt(
                            vendor,
                            "validation_failure",
                            f"value {value} outside reasonableness bound [{lo}, {hi}]",
                        )
                    )
                    raise ValidationFailure(
                        f"{vendor} returned {value!r} for {data_class.value}, outside "
                        f"the configured reasonableness bound [{lo}, {hi}]. Rejected — "
                        f"not silently substituted."
                    )

            if not is_primary and value is not None and comparison_key is not None:
                reference = self._recent_values.get(comparison_key)
                if reference is not None:
                    denom = abs(reference.value) if reference.value != 0 else 1.0
                    rel_diff = abs(value - reference.value) / denom
                    if rel_diff > self._divergence_threshold:
                        attempts.append(
                            FetchAttempt(
                                vendor,
                                "validation_failure",
                                f"value {value} vs {reference.value} from "
                                f"{reference.vendor} — rel diff {rel_diff:.2%}",
                            )
                        )
                        raise ValidationFailure(
                            f"Fallback vendor {vendor!r} returned {value!r} for "
                            f"{data_class.value}/{comparison_key!r}, which differs "
                            f"from the recent value {reference.value!r} reported by "
                            f"primary vendor {reference.vendor!r} by {rel_diff:.2%} "
                            f"(threshold {self._divergence_threshold:.2%}). A fallback "
                            f"returning a materially different value is a validation "
                            f"failure, not a silent substitution — refusing to return it."
                        )

            if value is not None and comparison_key is not None:
                self._recent_values[comparison_key] = _ReferenceValue(
                    value=value, vendor=vendor, observed_at=self._clock()
                )

            # Write-through: exactly one store.write call per successful fetch.
            self._store.write(records)

            attempts.append(FetchAttempt(vendor, "success"))
            return FetchResult(records=records, vendor=vendor, attempts=attempts)

        raise NoVendorAvailableError(
            f"no vendor in the fallback chain for {data_class.value} could serve "
            f"this request: {[(a.vendor, a.outcome) for a in attempts]}"
        )
