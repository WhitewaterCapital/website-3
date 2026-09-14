"""Alpaca Market Data API adapter — real 1-minute OHLCV bars for WW-CHAOS's
live-data gate.

## Why this file exists

`PLATFORM_REBUILD_PLAN.md`'s Roadblocks section ("WW-Chaos cannot go live")
established that Tiingo's free tier (the source every other live-gated
engine in this repo uses) is end-of-day daily bars only, and that WW-Chaos
needs genuine intraday (1-15 minute) bars — "a genuinely bigger, separate
build." This is that build, as far as one pass can genuinely take it.

## Research trail (2026-09-14) — what was actually checked, and how

Candidates checked against each provider's OWN current pricing/docs pages
(not stale training-data assumptions), via WebFetch (a separate network
path from this repo's own sandboxed shells — see below for why that
distinction matters):

  * **Alpaca Markets — Market Data API, "Basic" plan.** CONFIRMED FREE,
    confirmed via `docs.alpaca.markets/us/docs/about-market-data-api`
    fetched directly this pass: "Basic" is "the default option for both
    Paper and Live trading accounts" — a free PAPER account (no funding, no
    live brokerage relationship) is sufficient to get API keys with data
    access. Basic gives real-time + historical bars from the IEX feed only
    (not the SIP consolidated tape — that needs the paid "Algo Trader Plus"
    tier), historical data back to 2016, and a 200 requests/minute rate
    limit — comfortably enough for a 5-name watchlist. This is the adapter
    built below.
  * **Twelve Data — free "Basic" plan.** Per `twelvedata.com/pricing`
    (fetched this pass): 800 requests/day (8/min), and the `time_series`
    endpoint's own docs list `1min`/`5min`/... as supported `interval`
    values with no inline free-tier restriction found in the endpoint
    reference itself. Plausibly free for this use case, but NOT chosen as
    the primary build: Alpaca's docs were more explicit and unambiguous
    about the free tier's exact scope, and Alpaca is the more established
    choice in the quant/algo-trading community specifically for this
    "minute bars, no-cost, keys from a paper account" use case. Kept here
    as the honestly-documented runner-up, not silently dropped.
  * **Finnhub — free tier.** UNRESOLVED, not adopted. Finnhub's own
    `/stock/candle` endpoint docs page returned only page metadata to
    WebFetch (no endpoint body text came through), and a real anonymous
    probe this pass (`token=demo` against the real candle endpoint) came
    back `401` — i.e. reachable, but "demo" is not a working public token
    and no free-tier confirmation was obtained beyond that. A GitHub issue
    on finnhub's own repo (#349, "Intra-day with free access") shows a user
    getting only ~3 months of a requested 1-year 1-minute history back on
    what they believed was the free tier, with no maintainer response
    visible in what WebFetch returned — suggestive of a real restriction,
    not confirmed as one. Not built against, given Alpaca's cleaner
    confirmation.
  * **Polygon.io (now rebranded "Massive": `massive.com`).** Free "Basic"
    plan confirmed (`massive.com/pricing`, fetched this pass) to include
    minute aggregates for all US stock tickers, 2 years of history, 5 API
    calls/minute — but explicitly labelled "End of Day Data"; real-time /
    same-day intraday access needs the paid "Advanced" tier ($199/mo). This
    means Massive's free minute bars would be usable for a BACKTEST of
    WW-CHAOS's components on historical sessions, but NOT for a live
    same-day dislocation read — the whole point of this engine. Not built
    against for that reason, documented rather than silently skipped.
  * **Yahoo Finance (unofficial, e.g. via `yfinance`).** Deliberately NOT
    treated as equivalent to a real vendor API, per this task's own
    instruction. It is not a documented, supported API — no published SLA,
    no published rate limit, no Terms of Service that actually authorizes
    this kind of programmatic use (Yahoo's own ToS restricts automated
    data collection from its properties), and the endpoints `yfinance`
    scrapes have broken without notice before and will again. Flagged
    here, not adopted, and not silently treated as "basically the same as
    Alpaca" — it is a materially different risk category (ToS-ambiguous
    scraping vs. a documented, keyed, rate-limited API a vendor stands
    behind).

## What was ACTUALLY confirmed live this pass, vs. taken on faith from docs

Two separate network paths exist in this environment, with very different
reach:

  1. This repo's own sandboxed shells (this session's on-device shell
     included) hit the SAME proxy-level policy denial already documented
     throughout `PLATFORM_REBUILD_PLAN.md`'s Roadblocks for Tiingo/Alpha
     Vantage/iShares/FMP — confirmed freshly this pass, identically, for
     Alpaca, Twelve Data, AND Finnhub:

         $ curl -sv https://data.alpaca.markets/v2/stocks/AAPL/bars?...
         < HTTP/1.1 403 Forbidden
         < X-Proxy-Error: blocked-by-allowlist

     (byte-identical proxy response for api.twelvedata.com and finnhub.io).
     This is a genuine "cannot run from here" wall, not evidence the
     vendor itself is unreachable or broken.

  2. Anthropic's own WebFetch tooling — a genuinely separate network path,
     same one `cascade-data-engine`'s iShares adapter used to get its first
     real confirmation — DID reach both `data.alpaca.markets` and
     `finnhub.io` directly this pass and got real, live HTTP responses:
     a `401` (unauthorized — the real endpoint, correctly rejecting a
     request with no `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` headers) from
     Alpaca's real bars endpoint, and likewise a `401` from Finnhub's real
     candle endpoint with the placeholder `token=demo`. This CONFIRMS the
     Alpaca endpoint is live, reachable, and auth-gated exactly as
     documented — it does NOT confirm a successful, fully-parsed real
     response body, because no real Alpaca key was available in any
     sandbox this pass had access to. The exact JSON response SHAPE this
     adapter parses below (`{"bars": {"<SYM>": [{"t","o","h","l","c","v",
     "n","vw"}, ...]}, "next_page_token": ...}`) is taken from Alpaca's own
     published API reference and SDK conventions (stable, widely used,
     matches the `alpaca-py` client library's documented shape) — NOT from
     a raw payload this session actually held. That is a real, named gap,
     the same "confirmed reachable and documented, not confirmed
     byte-for-byte" gap `cascade-data-engine/cde/adapters/
     ishares_holdings.py`'s docstring names for the exact same reason.

## What this means for going live for real

Set both `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` (free — sign up at
https://alpaca.markets, a paper-only account is sufficient, no funding
required) in a gitignored `chaos-engine/.env`, and run `python3 -m
chaos.export` from a machine whose network is NOT behind this repo's own
sandboxed-shell proxy wall (i.e., Philip's own Mac, not this session's
on-device shell or its cloud workspace — both confirmed blocked above).
`export.py`'s gate (see that module) will then call this adapter for real.

## A real, load-bearing honesty caveat: IEX-only volume

The free Basic plan's feed is IEX ONLY, not the SIP consolidated tape. IEX
is one exchange among many and historically carries a small single-digit
percentage of total US equity consolidated volume — this has drifted over
the years and no current, verifiable figure is asserted here, but the
direction is unambiguous: **IEX volume is not total market volume.** WW-
CHAOS's `volume_surprise` component (`chaos/state.py::volume_surprise`) and
`order_flow_imbalance`'s tick-rule approximation are both computed
per-ticker against that ticker's OWN trailing IEX-only history (a z-score
against itself, not an absolute cross-vendor benchmark), so the z-scoring
itself is not mechanically broken by using IEX alone — but a human reading
"volume_z: 4.2" from a live IEX-sourced export should understand that
number describes an IEX-relative surprise, not a total-market one, and
that a genuinely different (SIP-fed, paid) feed would likely produce
different z-scores for the same real market moment. This is not raised as
a reason not to use IEX data — it is the confirmed free option — but as
the specific thing to not silently gloss over, per this repo's own honesty
discipline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from ..config import ALPACA_API_KEY_ID_VAR, ALPACA_API_SECRET_KEY_VAR, env

BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
DEFAULT_FEED = "iex"  # the only feed the free Basic plan actually serves
REQUEST_TIMEOUT_SECONDS = 30
MAX_PAGES = 50  # safety cap against a runaway pagination loop, not expected to bind
BAR_COLUMNS = ["open", "high", "low", "close", "volume"]
_EASTERN = ZoneInfo("America/New_York")

# Alpaca's own documented Basic-plan restriction: recent SIP data needs a
# paid subscription, and (per docs.alpaca.markets/us/docs/market-data-faq,
# fetched this pass) "the `end` parameter must be at least 15 minutes old to
# query SIP data without a subscription." This adapter requests the IEX feed
# specifically (not SIP), where this restriction is NOT confirmed to apply —
# but clipping `end` defensively costs nothing and avoids an avoidable 4xx
# if that turns out to bind on IEX too; the exact boundary was not verified
# against a real key this pass, so treat this constant as a documented,
# conservative guess, not a confirmed API rule.
_RECENT_DATA_BUFFER_MINUTES = 15


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without both `ALPACA_API_KEY_ID`
    and `ALPACA_API_SECRET_KEY` set. Named after the missing env var(s) so
    the fix is obvious from the message alone — same convention as every
    other adapter in this repo."""


class LiveFetchFailedError(RuntimeError):
    """Raised when both keys ARE set but the real HTTP call actually failed
    (network refused, non-200, unparsable body). Distinct from
    `VendorNotConfiguredError` on purpose — same convention as
    `cascade-data-engine/cde/adapters/ishares_holdings.py`: a caller who
    explicitly opted into live mode gets told the live call failed and why,
    never a silent downgrade to synthetic-demo data wearing a live label."""


def _to_rfc3339(dt: datetime) -> str:
    """Alpaca's documented timestamp format. Accepts naive datetimes (
    treated as UTC — callers in this codebase pass `datetime.now(timezone.
    utc)`-derived values) or timezone-aware ones (converted to UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bars_json_to_frame(bars: list[dict]) -> pd.DataFrame:
    """Convert Alpaca's per-symbol bar list (`[{"t","o","h","l","c","v",...}]`)
    into the exact OHLCV DataFrame shape `chaos/state.py` and `chaos/
    export.py::_synthetic_bars` already use: columns `open/high/low/close/
    volume`, a DatetimeIndex.

    Timezone handling matters here, concretely: Alpaca's `t` field is UTC
    (RFC-3339, e.g. "2026-09-11T13:30:00Z"). `chaos/state.py::
    volume_surprise` computes `minute-of-day = idx.hour * 60 + idx.minute`
    to compare each bar against the SAME minute-of-day across trailing
    sessions — if that index were left in UTC, every bar's minute-of-day
    would be shifted by the UTC-to-US/Eastern offset (4 or 5 hours
    depending on DST), silently breaking the U-shaped-volume-curve
    seasonal control the whole component depends on. So this function
    converts every timestamp to US/Eastern wall-clock time and DROPS the
    tzinfo (matching `_synthetic_bars`'s already-naive, already-Eastern-
    implicit timestamps) rather than leaving bars tz-aware in UTC."""
    if not bars:
        return pd.DataFrame(
            {c: pd.Series(dtype=float) for c in BAR_COLUMNS},
            index=pd.DatetimeIndex([], name="timestamp"),
        )
    idx = []
    cols: dict[str, list[float]] = {c: [] for c in BAR_COLUMNS}
    for b in bars:
        ts_utc = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        ts_eastern_naive = ts_utc.astimezone(_EASTERN).replace(tzinfo=None)
        idx.append(pd.Timestamp(ts_eastern_naive))
        cols["open"].append(float(b["o"]))
        cols["high"].append(float(b["h"]))
        cols["low"].append(float(b["l"]))
        cols["close"].append(float(b["c"]))
        cols["volume"].append(float(b["v"]))
    df = pd.DataFrame(cols, index=pd.DatetimeIndex(idx, name="timestamp")).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


class AlpacaBarsAdapter:
    """Real adapter against Alpaca's Market Data API — makes a genuine
    `requests.get` call when both keys are configured. See this module's
    docstring for the full research trail, what was actually confirmed
    live this pass vs. taken from documentation, and the IEX-only-volume
    honesty caveat."""

    name = "alpaca-iex-basic"

    def __init__(self) -> None:
        self._key_id = env(ALPACA_API_KEY_ID_VAR)
        self._secret_key = env(ALPACA_API_SECRET_KEY_VAR)

    def is_configured(self) -> bool:
        return bool(self._key_id) and bool(self._secret_key)

    def _require_keys(self) -> tuple[str, str]:
        if not self._key_id or not self._secret_key:
            missing = [
                name
                for name, val in (
                    (ALPACA_API_KEY_ID_VAR, self._key_id),
                    (ALPACA_API_SECRET_KEY_VAR, self._secret_key),
                )
                if not val
            ]
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable(s) "
                f"{', '.join(missing)} not set. Both are required (Alpaca "
                f"authenticates with a key-ID/secret PAIR, not a single "
                f"key). Get a free key pair at https://alpaca.markets — a "
                f"paper-only account is sufficient, no funding required — "
                f"and set both in a gitignored chaos-engine/.env. See the "
                f"module docstring at the top of "
                f"chaos/adapters/alpaca_bars.py for the confirmed evidence "
                f"behind this choice. No network call has been attempted."
            )
        return self._key_id, self._secret_key

    def fetch_minute_bars(
        self,
        tickers: list[str],
        start: datetime,
        end: datetime,
        feed: str = DEFAULT_FEED,
        limit: int = 10000,
    ) -> dict[str, pd.DataFrame]:
        """Real 1-minute OHLCV bars for every ticker in `tickers`, over
        `[start, end)`, from Alpaca's real `/v2/stocks/bars` endpoint —
        one paginated GET loop shared across the whole watchlist (Alpaca's
        multi-symbol bars endpoint takes a comma-joined `symbols` param and
        returns `{"bars": {"<SYM>": [...]}, "next_page_token": ...}`; this
        method follows `next_page_token` until it is null or `MAX_PAGES` is
        hit).

        Raises `VendorNotConfiguredError` if the keys are missing,
        `LiveFetchFailedError` if the keys ARE set but the real call fails
        for any reason (network error, non-2xx status, unparsable JSON, a
        response missing the `bars` key entirely). Never returns partial
        data silently mislabeled as complete — a mid-pagination failure
        raises rather than returning whatever pages happened to succeed."""
        key_id, secret_key = self._require_keys()

        now = datetime.now(timezone.utc)
        recent_cutoff = now.timestamp() - _RECENT_DATA_BUFFER_MINUTES * 60
        effective_end = end
        if effective_end.tzinfo is None:
            effective_end = effective_end.replace(tzinfo=timezone.utc)
        if effective_end.timestamp() > recent_cutoff:
            effective_end = datetime.fromtimestamp(recent_cutoff, tz=timezone.utc)

        headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        }
        params: dict[str, str | int] = {
            "symbols": ",".join(tickers),
            "timeframe": "1Min",
            "start": _to_rfc3339(start),
            "end": _to_rfc3339(effective_end),
            "feed": feed,
            "limit": limit,
            "adjustment": "raw",
        }

        raw_bars: dict[str, list[dict]] = {t: [] for t in tickers}
        page_token: str | None = None
        pages_fetched = 0

        while True:
            request_params = dict(params)
            if page_token:
                request_params["page_token"] = page_token
            try:
                resp = requests.get(
                    BASE_URL, params=request_params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
                )
            except requests.exceptions.RequestException as exc:
                raise LiveFetchFailedError(
                    f"{self.name}: real HTTP GET to {BASE_URL} failed: {exc!r}. If this is "
                    f"the same 'connection refused'/proxy-403 wall documented in this "
                    f"module's docstring, this must be run from an unrestricted network "
                    f"(not this repo's own sandboxed shells) — see the docstring for the "
                    f"confirmed evidence. No fallback was used; nothing was written."
                ) from exc

            if resp.status_code == 401 or resp.status_code == 403:
                raise LiveFetchFailedError(
                    f"{self.name}: {resp.status_code} from {BASE_URL} — credentials "
                    f"rejected. Check that both {ALPACA_API_KEY_ID_VAR} and "
                    f"{ALPACA_API_SECRET_KEY_VAR} are set correctly and the key pair "
                    f"hasn't been regenerated/revoked in the Alpaca dashboard."
                )
            if resp.status_code == 429:
                raise LiveFetchFailedError(
                    f"{self.name}: 429 rate-limited from {BASE_URL} — the free Basic "
                    f"plan's documented cap is 200 requests/minute; back off and retry."
                )
            if resp.status_code != 200:
                raise LiveFetchFailedError(
                    f"{self.name}: unexpected HTTP {resp.status_code} from {BASE_URL}: "
                    f"{resp.text[:500]!r}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise LiveFetchFailedError(
                    f"{self.name}: response from {BASE_URL} was not valid JSON ({exc!r})."
                ) from exc

            if "bars" not in payload:
                raise LiveFetchFailedError(
                    f"{self.name}: response from {BASE_URL} had no 'bars' key — the "
                    f"documented response shape this adapter parses may have drifted "
                    f"since this module's docstring was written. Raw keys present: "
                    f"{sorted(payload.keys())!r}"
                )

            for sym, rows in (payload.get("bars") or {}).items():
                raw_bars.setdefault(sym, []).extend(rows or [])

            page_token = payload.get("next_page_token")
            pages_fetched += 1
            if not page_token or pages_fetched >= MAX_PAGES:
                break

        return {t: _bars_json_to_frame(raw_bars.get(t, [])) for t in tickers}


def fetch_watchlist_minute_bars(
    tickers: list[str],
    lookback_days: int,
    feed: str = DEFAULT_FEED,
    adapter: AlpacaBarsAdapter | None = None,
) -> dict[str, pd.DataFrame]:
    """Convenience entry point mirroring `weekly-engine/wf/adapters/
    prices_tiingo.py::fetch_universe_weekly_prices` — one shared adapter
    instance, `end = now`, `start = now - lookback_days`. This is the one
    function `chaos/export.py`'s live gate calls; it has no idea whether
    the concrete adapter behind it makes a real HTTP call or (in a test)
    is swapped for a fake — same adapter-boundary discipline as every other
    live-gated engine here."""
    adapter = adapter or AlpacaBarsAdapter()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    return adapter.fetch_minute_bars(tickers, start=start, end=end, feed=feed)
