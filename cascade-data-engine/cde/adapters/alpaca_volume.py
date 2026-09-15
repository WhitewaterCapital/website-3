"""Alpaca Market Data API adapter — real DAILY OHLCV bars, used to compute a
trailing-N-day average dollar volume per constituent ("typical_volume", the
exact input name `quant-infra/cascade/pressure.py::compute_pressure`
expects) and, separately, a fund's own most-recent close/volume for
`estimate_flow_proxy`.

## Why this file exists

`cascade-data-engine/README.md`'s "still open" section documented that
`typical_volume` per constituent was not sourced anywhere in the prior
pass: this platform's usual volume vendor, Tiingo, is blocked from every
sandbox this engine has run in — a SEPARATE, independent block from the
`ishares.com` proxy wall documented in `adapters/ishares_holdings.py`.

`chaos-engine/chaos/adapters/alpaca_bars.py` (a different engine, built
concurrently this same pass) already did the real vendor research and
confirmed, via WebFetch against Alpaca's own current docs
(`docs.alpaca.markets/us/docs/about-market-data-api`), that Alpaca
Markets' free "Basic" Market Data API plan is genuinely free -- a paper
account (no funding, no live brokerage relationship) is sufficient for a
real key pair -- and gives real historical bars including volume, from the
IEX feed. THIS module relies on that confirmed-free-tier finding (it was
not independently re-run this pass; see `chaos/adapters/alpaca_bars.py`'s
own docstring for the full multi-vendor comparison and the exact evidence
trail), but is otherwise a wholly separate, wholly duplicated build -- see
"Sealed, not shared" below.

This module requests Alpaca's `timeframe=1Day` bars, NOT the `1Min` bars
`chaos-engine`'s adapter uses. That is a deliberate, different choice of
granularity: WW-Chaos needs genuine intraday reads for a same-day
dislocation signal, while a "typical volume" figure for a liquidity
denominator (`pressure_i = weight * flow / typical_volume_i`) is exactly
what a trailing daily average is for -- requesting minute bars and
aggregating them client-side would be strictly more requests for the same
answer, with no accuracy benefit for this specific use. The `1Day`
`timeframe` value is confirmed as valid REST API surface by Alpaca's own
published bars-endpoint reference (the same endpoint, same auth, same
response shape as the 1-minute case -- only the `timeframe` query
parameter changes) -- this is ordinary, stable API surface, not a
separately-gated capability, so it was not felt to need its own fresh
WebFetch pass beyond `chaos-engine`'s adapter's existing confirmation that
the vendor and endpoint are real and free.

## Sealed, not shared

Per this repo's standing convention (every engine here duplicates its own
`.env` loader rather than importing one -- see `cde/config.py`'s module
docstring), this module does NOT import anything from `chaos-engine`. The
two env var NAMES below (`ALPACA_API_KEY_ID_VAR`, `ALPACA_API_SECRET_KEY_VAR`)
are typed out here as the same string literals `chaos/config.py` uses
(`"ALPACA_API_KEY_ID"` / `"ALPACA_API_SECRET_KEY"`) -- intentionally
matching, so a member who configures one Alpaca key pair in either engine's
`.env` (or a shared shell environment) lights up both engines' live paths
-- but this is a deliberate, documented literal-string coincidence, not a
cross-engine dependency: nothing is imported from `chaos-engine`, and
nothing here would break if `chaos-engine` renamed its own constants
tomorrow.

## What was ACTUALLY confirmed vs. taken on faith

Everything in `chaos/adapters/alpaca_bars.py`'s own "What was ACTUALLY
confirmed live this pass" section applies identically here: this repo's
own sandboxed shells (this session's on-device shell included) hit the
same proxy-level policy denial for `data.alpaca.markets` that blocks every
other market-data vendor documented in `PLATFORM_REBUILD_PLAN.md`'s
Roadblocks -- re-confirmed for THIS module by the fact that its own gate
tests (see `tests/test_alpaca_volume.py`) can only exercise the
gate/error-shape, never a byte-for-byte real response, from any sandbox
this pass had access to. The exact JSON response shape parsed below
(`{"bars": {"<SYM>": [{"t","o","h","l","c","v",...}]}, "next_page_token":
...}`) is taken from Alpaca's own published API reference (same shape
`chaos-engine`'s adapter parses for 1-minute bars -- only the `timeframe`
request parameter differs) -- not from a raw payload this module has
itself held.

## Going live for real

Set both `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` (free -- sign up
at https://alpaca.markets, a paper-only account is sufficient) in a
gitignored `cascade-data-engine/.env`, and run this from a machine whose
network is NOT behind this repo's own sandboxed-shell proxy wall (Philip's
own Mac, not this session's on-device shell or its cloud workspace -- both
confirmed blocked, identically to `ishares_holdings.py`'s own evidence).
`cde/export.py`'s live path will then call this adapter for real.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ..config import env

# Intentionally the same string literals as chaos/config.py's
# ALPACA_API_KEY_ID_VAR / ALPACA_API_SECRET_KEY_VAR -- see module
# docstring's "Sealed, not shared" section for why this is a deliberate
# duplication, not an import.
ALPACA_API_KEY_ID_VAR = "ALPACA_API_KEY_ID"
ALPACA_API_SECRET_KEY_VAR = "ALPACA_API_SECRET_KEY"

BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
DEFAULT_FEED = "iex"  # the only feed the free Basic plan actually serves
DEFAULT_LOOKBACK_DAYS = 21  # ~1 trading month of daily bars
REQUEST_TIMEOUT_SECONDS = 30
MAX_PAGES = 10  # safety cap against a runaway pagination loop, not expected to bind


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without both `ALPACA_API_KEY_ID`
    and `ALPACA_API_SECRET_KEY` set. Same convention as every other adapter
    in this repo, including `chaos-engine`'s own (independently defined,
    not shared) exception of the same name."""


class LiveFetchFailedError(RuntimeError):
    """Raised when both keys ARE set but the real HTTP call actually failed
    (network refused, non-200, unparsable body). A caller who explicitly
    opted into live mode gets told the live call failed and why, never a
    silent downgrade to a fabricated typical_volume."""


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaDailyVolumeAdapter:
    """Real adapter against Alpaca's Market Data API `1Day` bars -- makes a
    genuine `urllib` GET when both keys are configured. See this module's
    docstring for the full research trail and the sealed-not-shared note on
    the env var names."""

    name = "alpaca-iex-basic-daily-volume"

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
                f"authenticates with a key-ID/secret PAIR). Get a free key pair at "
                f"https://alpaca.markets -- a paper-only account is sufficient, no "
                f"funding required -- and set both in a gitignored "
                f"cascade-data-engine/.env. These are the SAME two env var names "
                f"chaos-engine/chaos/adapters/alpaca_bars.py uses (intentionally -- "
                f"see this module's docstring), so a key pair configured for one "
                f"engine also lights up this one. No network call has been attempted."
            )
        return self._key_id, self._secret_key

    def fetch_daily_bars(
        self,
        tickers: list[str],
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        feed: str = DEFAULT_FEED,
    ) -> dict[str, list[dict]]:
        """Real daily (`timeframe=1Day`) OHLCV bars for every ticker in
        `tickers`, over the trailing `lookback_days` calendar days, from
        Alpaca's real `/v2/stocks/bars` endpoint (paginated on
        `next_page_token`, same as `chaos-engine`'s adapter). Returns raw
        per-symbol bar-dict lists (`{"t","o","h","l","c","v",...}`), NOT a
        DataFrame -- this module has no `pandas` requirement of its own, and
        both callers below (`compute_typical_dollar_volume`,
        `latest_price_and_volume`) only need `c` (close) and `v` (volume).

        Raises `VendorNotConfiguredError` if the keys are missing,
        `LiveFetchFailedError` if the keys ARE set but the real call fails
        for any reason. Never returns partial data silently mislabeled as
        complete -- a mid-pagination failure raises rather than returning
        whatever pages happened to succeed."""
        key_id, secret_key = self._require_keys()

        end = datetime.now(timezone.utc)
        # Calendar-day buffer, not trading-day: weekends/holidays mean
        # `lookback_days` calendar days back yields fewer than
        # `lookback_days` actual daily bars, which is fine -- the average
        # below divides by however many bars actually came back, not by
        # `lookback_days` itself.
        start = end - timedelta(days=lookback_days)

        headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        }
        base_params: dict[str, str | int] = {
            "symbols": ",".join(tickers),
            "timeframe": "1Day",
            "start": _to_rfc3339(start),
            "end": _to_rfc3339(end),
            "feed": feed,
            "limit": 10000,
            "adjustment": "raw",
        }

        raw_bars: dict[str, list[dict]] = {t: [] for t in tickers}
        page_token: str | None = None
        pages_fetched = 0

        while True:
            params = dict(base_params)
            if page_token:
                params["page_token"] = page_token
            url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                    raw = resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise LiveFetchFailedError(
                        f"{self.name}: {exc.code} from {BASE_URL} -- credentials rejected. "
                        f"Check that both {ALPACA_API_KEY_ID_VAR} and "
                        f"{ALPACA_API_SECRET_KEY_VAR} are set correctly and the key pair "
                        f"hasn't been regenerated/revoked in the Alpaca dashboard."
                    ) from exc
                if exc.code == 429:
                    raise LiveFetchFailedError(
                        f"{self.name}: 429 rate-limited from {BASE_URL} -- the free Basic "
                        f"plan's documented cap is 200 requests/minute; back off and retry."
                    ) from exc
                raise LiveFetchFailedError(
                    f"{self.name}: unexpected HTTP {exc.code} from {BASE_URL}: "
                    f"{exc.read()[:500]!r}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise LiveFetchFailedError(
                    f"{self.name}: real HTTP GET to {BASE_URL} failed: {exc!r}. If this is "
                    f"the same 'connection refused'/proxy-403 wall documented in this "
                    f"module's docstring, this must be run from an unrestricted network "
                    f"(not this repo's own sandboxed shells). No fallback was used; "
                    f"nothing was written."
                ) from exc

            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise LiveFetchFailedError(
                    f"{self.name}: response from {BASE_URL} was not valid JSON ({exc!r})."
                ) from exc

            if "bars" not in payload:
                raise LiveFetchFailedError(
                    f"{self.name}: response from {BASE_URL} had no 'bars' key -- the "
                    f"documented response shape this adapter parses may have drifted. "
                    f"Raw keys present: {sorted(payload.keys())!r}"
                )

            for sym, rows in (payload.get("bars") or {}).items():
                raw_bars.setdefault(sym, []).extend(rows or [])

            page_token = payload.get("next_page_token")
            pages_fetched += 1
            if not page_token or pages_fetched >= MAX_PAGES:
                break

        return raw_bars

    def compute_typical_dollar_volume(
        self,
        tickers: list[str],
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        feed: str = DEFAULT_FEED,
    ) -> dict[str, float]:
        """Average(close * volume) over whatever trailing daily bars Alpaca
        actually returns, per ticker -- the exact `typical_volume` shape
        `pressure.py::compute_pressure` expects (a `Mapping[str, float]`).

        A ticker with zero usable bars returned is OMITTED from the result
        entirely (never a fabricated 0.0 or NaN entry) -- `compute_pressure`
        already treats a MISSING `typical_volume` entry as "exclude this
        leg, record why in `warnings`", the exact same honest-abstention
        contract this adapter relies on rather than reimplementing."""
        raw_bars = self.fetch_daily_bars(tickers, lookback_days=lookback_days, feed=feed)
        out: dict[str, float] = {}
        for ticker, rows in raw_bars.items():
            dollar_vols: list[float] = []
            for bar in rows:
                try:
                    dollar_vols.append(float(bar["c"]) * float(bar["v"]))
                except (KeyError, TypeError, ValueError):
                    continue  # a malformed bar is skipped, not allowed to poison the average
            if dollar_vols:
                out[ticker] = sum(dollar_vols) / len(dollar_vols)
        return out

    def latest_price_and_volume(
        self, tickers: list[str], feed: str = DEFAULT_FEED
    ) -> dict[str, tuple[float, float]]:
        """Most recent daily bar's (close, volume) per ticker -- used to feed
        `pressure.py::estimate_flow_proxy`'s `price`/`volume_shares`
        arguments for a FUND's own ticker (e.g. IVV itself, not its
        constituents) when no prior-day shares-outstanding snapshot exists
        yet for the direct flow method. A short (5-day) lookback is used
        since only the single most recent bar is needed. Ticker omitted if
        zero bars returned."""
        raw_bars = self.fetch_daily_bars(tickers, lookback_days=5, feed=feed)
        out: dict[str, tuple[float, float]] = {}
        for ticker, rows in raw_bars.items():
            if not rows:
                continue
            last = rows[-1]
            try:
                out[ticker] = (float(last["c"]), float(last["v"]))
            except (KeyError, TypeError, ValueError):
                continue
        return out


def fetch_typical_dollar_volume(
    tickers: list[str],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    adapter: AlpacaDailyVolumeAdapter | None = None,
) -> dict[str, float]:
    """Convenience entry point mirroring `chaos/adapters/alpaca_bars.py::
    fetch_watchlist_minute_bars` -- one shared adapter instance. This is the
    function `cde/export.py`'s live path calls; it has no idea whether the
    concrete adapter behind it makes a real HTTP call or (in a test) is
    swapped for a fake."""
    adapter = adapter or AlpacaDailyVolumeAdapter()
    return adapter.compute_typical_dollar_volume(tickers, lookback_days=lookback_days)
