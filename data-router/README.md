# Data Router

The one internal service every model in this codebase calls for data. No
model ever imports a vendor SDK, holds a vendor API key, or branches on a
vendor's name — it asks the router for a data class (`bars`, `fundamentals`,
`corporate_actions`, `holdings`, `news`, `macro`) and gets back records that
are always fully provenance-stamped, always validated, and always written
through to point-in-time storage before they're returned.

> **No live vendor call has ever been made against this code.** This sandbox
> has no network access and no real vendor credentials (Alpha Vantage,
> OpenBB, Tiingo). Every test in `tests/` runs against a local JSON-fixture
> adapter (`router/adapters/local_file.py`) standing in for a real vendor.
> See **What is NOT possible here** below for exactly what that does and
> doesn't prove.

## Why this exists

Straight from the spec this package implements: *"One internal service
every model calls for data. It picks the vendor, enforces the budget,
caches, validates and writes into point in time storage. No model ever
holds a vendor key or knows a vendor's name."* Everything below is in
service of that one sentence.

## What's built and fully tested (105 tests, 0 failures)

Run them:
```bash
python3 /home/claude/repo/_pyshim/run_tests.py $(pwd) tests
```
(or, wherever the shim lives relative to this checkout: `python3
<path-to-pyshim>/run_tests.py <path-to-data-router> tests`.)

| Module | What it does | Tested by |
|---|---|---|
| `router/schema.py` | One dataclass per data class (`Bar`, `FundamentalFact`, `CorporateAction`, `Holding`, `NewsItem`, `MacroObservation`), all inheriting `ProvenanceMixin` — five required fields (`observation_date`, `source_publication_time`, `ingestion_time`, `vendor`, `vendor_field_name`) enforced two ways: Python's own `TypeError` if a field is omitted, `MissingProvenanceError` if it's passed as `None`/blank. | `tests/test_schema.py` |
| `router/adapters/base.py` | The `Adapter` ABC every vendor implements — one `get_*` method per data class, a `capabilities` set the router checks before ever calling a method. | `tests/test_adapters.py`, `tests/test_router.py` |
| `router/adapters/local_file.py` | **The one real, functional adapter.** Reads synthetic JSON fixtures (`router/adapters/fixtures/*.json` — every value made up) and returns fully provenance-stamped records. Exists purely to exercise the router end to end without a network. | `tests/test_adapters.py` |
| `router/adapters/alpha_vantage.py`, `openbb.py`, `tiingo.py` | Real-vendor **stubs**. Each raises `VendorNotConfiguredError`, naming the missing env var, whether or not that env var happens to be set — because even with a key, no HTTP call is implemented in this sandbox. Zero network imports (verified by AST, not just grep — see `test_alpha_vantage_stub_never_imports_a_network_library`). | `tests/test_adapters.py` |
| `router/quota.py` | Per-vendor token bucket, per-minute **and** per-day limits enforced together (an atomic check-then-consume against both), plus `PriorityRequestQueue` — a chaos request never queues behind a bulk backfill even if the backfill arrived first. | `tests/test_quota.py` |
| `router/circuit.py` | Circuit breaker: `CLOSED → OPEN (tripped) → OPEN (cooldown) → HALF_OPEN (probe) → CLOSED (recovered)`, or back to `OPEN` if the probe itself fails. Every transition appends to an event log (and calls an optional callback) — the spec's "a simple callback or event-log list is fine". | `tests/test_circuit.py` |
| `router/router.py` (`DataRouter`) | Walks a documented fallback chain per data class; skips a vendor whose circuit is open or whose quota is exhausted; on adapter failure, records a circuit-breaker failure and fails over; **validates, never silently substitutes** — a fallback value that diverges from a recent primary-vendor value (or falls outside a configured reasonableness bound) raises `ValidationFailure` instead of being returned; writes through to the point-in-time store **exactly once** per successful `fetch()`. | `tests/test_router.py` |
| `router/store.py` (`PointInTimeStore`) | A small `Protocol` (mirrors `engine/incepta/store/base.py`'s shape) plus `InMemoryPointInTimeStore`, a reference implementation for tests/local dev. Swapping in the engine's real DuckDB/Supabase store means implementing this one `write()` method — no router change. | `tests/test_router.py` |
| `router/universe.py` (DATA-02) | `UniverseBuilder.universe_as_of(date)` built from a membership table (`ticker, entry_date, exit_date`) plus an optional liquidity floor, and `TradingCalendar`, built from a **supplied** holiday list — never computed at runtime. | `tests/test_universe.py`, including the doc's own named survivorship test |
| `router/cost.py` | Pure per-`(vendor, model)` request/cost counter (`CostMeter`) and `project_cost(current_rate, plan_limit) → {over_budget, headroom, utilization, ...}`. | `tests/test_cost.py` |
| `router/indicators.py` | SMA, EMA, RSI (Wilder-smoothed), MACD — computed **locally from bars**, never from a vendor's own indicator endpoint. Pure functions over `list[float]`, plus `*_from_bars` convenience wrappers over `list[Bar]`. | `tests/test_indicators.py` |

### The named survivorship test (DATA-02)

`tests/test_universe.py::test_survivorship_delisted_name_included_before_exit_and_excluded_after_exit_date`
builds a synthetic membership table with a name (`DELIST1`) that entered in
2015 and was delisted on 2019-06-01, then asserts:
- `universe_as_of(2018-01-01)` **includes** `DELIST1` — it was a real,
  tradeable member on that past date.
- `universe_as_of(2019-06-01)` and later **excludes** it.

Silently dropping a since-delisted name from a historical universe query is
exactly how survivorship bias enters a backtest; this is the one test that
exists specifically to catch that regression.

### The named validation rule (fallback divergence)

`tests/test_router.py::test_fallback_with_wildly_different_value_raises_validation_failure_not_silent_substitution`
seeds a recent primary-vendor value of `100.0`, then makes the only
available fallback vendor return `9999.0` for the same key. `DataRouter.fetch`
raises `ValidationFailure` rather than returning the divergent value — per
the spec: *"a fallback returning a materially different value is a
validation failure and not a silent substitution."* The threshold is
`divergence_threshold` (default 5% relative difference), configurable per
`DataRouter` instance; a fallback within threshold
(`test_fallback_within_threshold_is_accepted`) is returned normally. A
`reasonableness_bound=(lo, hi)` additionally catches an out-of-band value
even with **no** prior reference at all (the very first call for a key).

### Write-through, exactly once

`tests/test_router.py::test_successful_fetch_results_in_exactly_one_write_call`
asserts `store.write_calls == 1` after one successful `fetch()` — and
`test_a_failed_fetch_writes_nothing` asserts a fetch that exhausts the whole
fallback chain writes nothing at all.

## What is explicitly NOT possible here

- **No real vendor call has ever been executed against this code, anywhere,
  under any test.** There is no network access in this sandbox, and no real
  Alpha Vantage / OpenBB / Tiingo credentials exist for it.
- `router/adapters/alpha_vantage.py`, `openbb.py`, and `tiingo.py` are
  **stubs**, not integrations. Each `get_*` method raises
  `VendorNotConfiguredError` (no key) or `NotImplementedError` (key present
  but the real HTTP call was never written, because it could never be
  tested here) — never a real request. `tests/test_adapters.py` proves this
  two ways: (1) an AST walk of `alpha_vantage.py` confirms it contains no
  `import requests`/`httpx`/`urllib`/`socket` statement anywhere, and (2) a
  test that sets a fake env-var key and confirms the method still raises
  `NotImplementedError` rather than attempting anything — configuring a key
  changes *which* stub exception you get, never whether a network call
  happens.
- Consequently: nothing here has been validated against real vendor response
  shapes, real rate-limit headers, real API error codes, or real market
  data. The fixture data in `router/adapters/fixtures/*.json` is entirely
  made up (plausible AAPL/MSFT-shaped numbers, not real prices).
- The quota manager's token-bucket **math** is tested exhaustively with an
  injectable clock; it has never been exercised against a real vendor's
  actual rate-limit behavior (which sometimes differs from its documented
  limits in practice).
- `router/universe.py`'s membership and liquidity tables are synthetic
  inputs the caller supplies — there is no live index-membership feed or
  liquidity vendor wired up, and none is claimed.

## The extension point: wiring up a real vendor

Adding a real vendor is **one new adapter class** — no router change, no
model change, no schema change. Concretely, to make Alpha Vantage real:

1. Set `ALPHA_VANTAGE_API_KEY` in a gitignored `data-router/.env`
   (`router/config.py` already loads it, mirroring
   `engine/incepta/config.py`'s `_load_dotenv()` pattern exactly — same
   format, same "never commit a key" discipline).
2. In `router/adapters/alpha_vantage.py`, replace each method's
   `raise NotImplementedError(...)` (after the existing `self._require_key()`
   check, which stays) with a real HTTP call — e.g.
   `requests.get("https://www.alphavantage.co/query", params={...})` — then
   map the response into the matching `router.schema` class, filling in
   `vendor="alpha-vantage"` and `vendor_field_name` with Alpha Vantage's own
   field name (e.g. `"4. close"`) so a mapping bug is traceable to the exact
   source field.
3. Register the new/real adapter instance in the `adapters` dict passed to
   `DataRouter`, and add `"alpha-vantage"` to the relevant data class's entry
   in `fallback_chains` wherever it should sit in priority order. Configure
   its limits with `QuotaManager.configure(...)` and give it a
   `CircuitBreaker`. Nothing in `router.py`, `quota.py`, `circuit.py`, or any
   model changes.
4. **Do not** wire up Alpha Vantage's own technical-indicator endpoints
   (SMA/RSI/MACD/etc.) — only its raw bars/fundamentals/news endpoints. All
   indicators are computed locally from bars by `router/indicators.py`, per
   the spec, so every model sees the same indicator math regardless of which
   vendor served the underlying bars.
5. The same four steps apply verbatim to `router/adapters/openbb.py` and
   `router/adapters/tiingo.py` for their respective env vars
   (`OPENBB_API_KEY`, `TIINGO_API_KEY`).

### Reality-check numbers for whoever does step 2 (verify before relying on these — terms change)

- Alpha Vantage free tier: **~25 requests/day**, no published per-minute cap
  beyond that.
- Alpha Vantage's cheapest paid tier: **~75 requests/minute**.

These are exactly the two numbers `QuotaManager.configure(vendor,
per_minute=..., per_day=...)` exists to enforce — see `router/quota.py`.

## Architecture at a glance

```
model code
    │  DataRouter.fetch(DataClass.BARS, {"ticker": "AAPL", ...})
    ▼
DataRouter                                   (router/router.py)
    │  walks fallback_chains[DataClass.BARS] = ["primary", "backup", ...]
    │
    ├─▶ CircuitBreaker.allow_request()?  no → skip to next vendor
    │       (router/circuit.py)
    │
    ├─▶ QuotaManager.try_consume(vendor)? no → skip to next vendor
    │       (router/quota.py: per-minute AND per-day token buckets)
    │
    ├─▶ Adapter.get_bars(...)                (router/adapters/*.py)
    │       raises → CircuitBreaker.record_failure(), skip to next vendor
    │       succeeds → CircuitBreaker.record_success()
    │
    ├─▶ divergence / reasonableness check    (fallback only)
    │       materially different from a recent primary value, or outside a
    │       configured bound → raise ValidationFailure, DO NOT return it
    │
    ├─▶ PointInTimeStore.write(records)      (router/store.py) — exactly once
    │
    ▼
list[Bar | FundamentalFact | ...]  — every record carries full provenance
    (router/schema.py: observation_date, source_publication_time,
     ingestion_time, vendor, vendor_field_name)
```

Separately, `router/universe.py` answers "what tickers existed as of this
past date" (survivorship-safe) and `router/indicators.py` computes technical
indicators from whatever bars the router already returned — neither talks to
a vendor at all.

Request-priority arbitration under quota contention
(`router/quota.py:PriorityRequestQueue`) is a deliberately separate concern
from `DataRouter` itself: a deployment with many concurrent callers puts a
dispatcher in front of `DataRouter.fetch` that pops requests from the
priority queue (chaos-engine pulls ahead of bulk backfills, regardless of
arrival order) and calls `fetch` once per request. `DataRouter` stays a
synchronous, single-request function so its vendor-selection and validation
logic is simple to test in isolation.

## Layout

```
data-router/
├── README.md                      (this file)
├── router/
│   ├── schema.py                  data classes + ProvenanceMixin
│   ├── config.py                  .env loading (mirrors engine/incepta/config.py)
│   ├── store.py                   PointInTimeStore Protocol + in-memory reference impl
│   ├── quota.py                   TokenBucket, QuotaManager, PriorityRequestQueue
│   ├── circuit.py                 CircuitBreaker
│   ├── router.py                  DataRouter — the one service models call
│   ├── universe.py                DATA-02: UniverseBuilder, TradingCalendar
│   ├── cost.py                    CostMeter, project_cost
│   ├── indicators.py              SMA / EMA / RSI / MACD, computed from bars
│   └── adapters/
│       ├── base.py                Adapter ABC, DataClass enum
│       ├── local_file.py          the one real adapter (JSON fixtures)
│       ├── alpha_vantage.py       stub + extension-point docstring
│       ├── openbb.py              stub
│       ├── tiingo.py              stub
│       └── fixtures/*.json        synthetic bars/fundamentals/etc. — all made up
└── tests/
    ├── test_schema.py
    ├── test_adapters.py
    ├── test_quota.py
    ├── test_circuit.py
    ├── test_router.py
    ├── test_universe.py
    ├── test_cost.py
    └── test_indicators.py
```
