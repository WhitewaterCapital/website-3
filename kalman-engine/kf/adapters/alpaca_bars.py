"""Alpaca Market Data API adapter — real DAILY closing prices for
WW-KALMAN's live-data gate. Sealed duplicate (NOT an import) of the same
pattern chaos-engine/chaos/adapters/alpaca_bars.py and cascade-data-engine/
cde/adapters/alpaca_volume.py already built and confirmed this session —
see either module's own docstring for the full multi-vendor research trail
(Alpaca's free "Basic" Market Data API plan confirmed genuinely free via a
paper-only account, IEX feed, no funding required) that this module relies
on rather than re-running from scratch. This engine is SEALED (see kf/
config.py's module docstring) — nothing here is imported from either of
those two modules, even though the logic is close to identical; the two
env var names below are the same literal strings by deliberate convention,
not a shared dependency.

This module requests `timeframe=1Day` bars (same choice, same justification,
as cascade-data-engine's alpaca_volume.py): a pairs-trading Kalman filter
needs a daily closing-price series over many months, not intraday bars —
requesting minute bars and aggregating client-side would be strictly more
requests for a strictly worse-suited answer.

## What was ACTUALLY confirmed live this pass, vs. taken on faith

This module was NOT independently re-verified against a live Alpaca
response this pass (no sandbox this engine has been built in has network
access to data.alpaca.markets — see chaos-engine's adapter docstring for
the exact proxy-403 evidence, re-confirmed identically for every other
engine's Alpaca adapter this session). It relies on the SAME confirmed-free,
confirmed-real-endpoint finding chaos-engine's and cascade-data-engine's
adapters already established via WebFetch against Alpaca's own docs. The
JSON response shape parsed below (`{"bars": {"<SYM>": [{"t","o","h","l","c",
"v",...}]}, "next_page_token": ...}`) is Alpaca's own documented, stable
bars-endpoint shape — not a payload this module has itself held.

## Going live for real

Set both `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` (free — sign up at
https://alpaca.markets, a paper-only account is sufficient, no funding
required) in a gitignored `kalman-engine/.env`, and run `python3 -m
kf.export` from a machine whose network is NOT behind this repo's own
sandboxed-shell proxy wall (Philip's own Mac, not this session's on-device
shell or its cloud workspace — both confirmed blocked for every other
engine's identical Alpaca adapter this session).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ..config import env

# Intentionally the same string literals as chaos/config.py's /
# cde/adapters/alpaca_volume.py's ALPACA_API_KEY_ID_VAR / ALPACA_API_SECRET_KEY_VAR.
# See module docstring's sealed-not-shared note.
ALPACA_API_KEY_ID_VAR = "ALPACA_API_KEY_ID"
ALPACA_API_SECRET_KEY_VAR = "ALPACA_API_SECRET_KEY"

BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
DEFAULT_FEED = "iex"  # the only feed the free Basic plan actually serves
REQUEST_TIMEOUT_SECONDS = 30
MAX_PAGES = 10


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without both env vars set. Same
    convention (and same message shape) as every other Alpaca adapter in
    this repo, independently defined here — this engine is sealed."""


class LiveFetchFailedError(RuntimeError):
    """Raised when both keys ARE set but the real HTTP call itself failed.
    Distinct from VendorNotConfiguredError on purpose: a caller who
    explicitly opted into live mode is told the live call failed and why,
    never silently downgraded to synthetic data wearing a live label."""


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaDailyCloseAdapter:
    """Real adapter against Alpaca's Market Data API `1Day` bars — makes a
    genuine `urllib` GET when both keys are configured. See module
    docstring for the full research trail this relies on."""

    name = "alpaca-iex-basic-daily-close"

    def __init__(self) -> None:
        self._key_id = env(ALPACA_API_KEY_ID_VAR)
        self._secret_key = env(ALPACA_API_SECRET_KEY_VAR)

    def is_configured(self) -> bool:
        return bool(self._key_id) and bool(self._secret_key)

    def _require_keys(self) -> tuple[str, str]:
        if not self._key_id or not self._secret_key:
            missing = [
                name for name, val in (
                    (ALPACA_API_KEY_ID_VAR, self._key_id),
                    (ALPACA_API_SECRET_KEY_VAR, self._secret_key),
                ) if not val
            ]
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable(s) "
                f"{', '.join(missing)} not set. Both are required. Get a free key "
                f"pair at https://alpaca.markets -- a paper-only account is "
                f"sufficient, no funding required -- and set both in a gitignored "
                f"kalman-engine/.env. Same two env var names every other Alpaca "
                f"adapter in this repo uses, intentionally. No network call has "
                f"been attempted."
            )
        return self._key_id, self._secret_key

    def fetch_daily_closes(
        self,
        tickers: list[str],
        lookback_days: int,
        feed: str = DEFAULT_FEED,
    ) -> dict[str, dict[str, float]]:
        """Real daily closing prices for every ticker in `tickers`, over the
        trailing `lookback_days` calendar days, from Alpaca's real
        `/v2/stocks/bars` endpoint. Returns `{ticker: {date_iso: close}}` —
        a plain dict, not a DataFrame, since kf/export.py aligns multiple
        tickers' dates itself (some tickers may have bars on days others are
        missing, e.g. a data gap — the caller decides how to handle that,
        this adapter just reports what Alpaca returned).

        Raises `VendorNotConfiguredError` if the keys are missing,
        `LiveFetchFailedError` if the keys ARE set but the real call fails
        for any reason. Never returns partial data silently mislabeled as
        complete -- a mid-pagination failure raises rather than returning
        whatever pages happened to succeed."""
        key_id, secret_key = self._require_keys()

        end = datetime.now(timezone.utc)
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
                        f"{self.name}: {exc.code} from {BASE_URL} -- credentials "
                        f"rejected. Check that both {ALPACA_API_KEY_ID_VAR} and "
                        f"{ALPACA_API_SECRET_KEY_VAR} are set correctly."
                    ) from exc
                if exc.code == 429:
                    raise LiveFetchFailedError(
                        f"{self.name}: 429 rate-limited from {BASE_URL} -- the free "
                        f"Basic plan's documented cap is 200 requests/minute."
                    ) from exc
                raise LiveFetchFailedError(
                    f"{self.name}: unexpected HTTP {exc.code} from {BASE_URL}: "
                    f"{exc.read()[:500]!r}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise LiveFetchFailedError(
                    f"{self.name}: real HTTP GET to {BASE_URL} failed: {exc!r}. If "
                    f"this is the same proxy-403 wall documented throughout this "
                    f"repo's other Alpaca adapters, run this from an unrestricted "
                    f"network (Philip's own Mac), not this repo's own sandboxed "
                    f"shells. No fallback was used; nothing was written."
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
                    f"documented response shape may have drifted. Raw keys present: "
                    f"{sorted(payload.keys())!r}"
                )

            for sym, rows in (payload.get("bars") or {}).items():
                raw_bars.setdefault(sym, []).extend(rows or [])

            page_token = payload.get("next_page_token")
            pages_fetched += 1
            if not page_token or pages_fetched >= MAX_PAGES:
                break

        out: dict[str, dict[str, float]] = {}
        for ticker, rows in raw_bars.items():
            by_date: dict[str, float] = {}
            for bar in rows:
                try:
                    date_iso = str(bar["t"])[:10]  # RFC3339 date prefix
                    by_date[date_iso] = float(bar["c"])
                except (KeyError, TypeError, ValueError):
                    continue
            out[ticker] = by_date
        return out


def fetch_universe_daily_closes(
    tickers: list[str],
    lookback_days: int,
    adapter: AlpacaDailyCloseAdapter | None = None,
) -> dict[str, dict[str, float]]:
    """Convenience entry point mirroring every other engine's own
    fetch_* wrapper — one shared adapter instance, so kf/export.py's live
    path has no idea whether the concrete adapter makes a real HTTP call or
    (in a test) is swapped for a fake."""
    adapter = adapter or AlpacaDailyCloseAdapter()
    return adapter.fetch_daily_closes(tickers, lookback_days=lookback_days)
