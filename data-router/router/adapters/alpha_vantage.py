"""Alpha Vantage adapter STUB — the extension point for a real vendor.

This file intentionally makes ZERO network calls, anywhere, ever. There is no
`import requests`, no `urllib`, no `httpx` in this module. Every public method
raises `VendorNotConfiguredError` naming the missing env var, because this
sandbox has no network access and no real Alpha Vantage key — so pretending
otherwise would be dishonest about what has actually been exercised.

Reality-check numbers worth remembering for whoever wires up the real call
(source: Alpha Vantage's own published limits at the time the router's
planning doc was written — verify current terms before relying on these):
  - Free tier:        25 requests/day, no per-minute cap published beyond that.
  - Cheapest paid tier: ~75 requests/minute.
These are exactly the kind of numbers `router.quota.TokenBucket` exists to
enforce per vendor per minute AND per day — see `router/quota.py`.

### To make this a REAL adapter later:

1. Set `ALPHA_VANTAGE_API_KEY` in a gitignored `data-router/.env`
   (`router/config.py` already loads it — same pattern as
   `engine/incepta/config.py`).
2. In each `get_*` method below, replace the `VendorNotConfiguredError` raise
   (once the key check passes) with an actual HTTP call — e.g.
   `requests.get("https://www.alphavantage.co/query", params={...})` — parse
   the response, and map each field into the matching `router.schema` class,
   filling `vendor="alpha-vantage"` and `vendor_field_name=<AV's own field
   name>` (e.g. `"4. close"`).
3. Nothing else changes. `router.router.DataRouter` only ever calls
   `Adapter.get_*` and only ever sees `router.schema` objects — it has no idea
   whether the concrete class behind `Adapter` makes an HTTP call or reads a
   JSON fixture. That is the entire point of the adapter boundary.
4. Do NOT compute technical indicators from anything this adapter returns
   from Alpha Vantage's indicator endpoints (SMA/RSI/MACD/etc.) — the spec is
   explicit that the router computes all technical indicators locally from
   bars and never consumes vendor-computed indicators. Only wire up the raw
   bars/fundamentals/news endpoints here.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..schema import Bar, CorporateAction, FundamentalFact, MacroObservation, NewsItem
from .base import Adapter, DataClass, VendorNotConfiguredError
from ..config import env

REQUIRED_ENV_VAR = "ALPHA_VANTAGE_API_KEY"


class AlphaVantageAdapter(Adapter):
    """Stub. Declares the capabilities a real Alpha Vantage integration would
    have; every method raises `VendorNotConfiguredError` because no key is
    (or can be) configured in this sandbox, and no network call is ever
    attempted here regardless."""

    name = "alpha-vantage"
    capabilities = frozenset(
        {
            DataClass.BARS,
            DataClass.FUNDAMENTALS,
            DataClass.CORPORATE_ACTIONS,
            DataClass.NEWS,
            DataClass.MACRO,
        }
    )

    def __init__(self) -> None:
        self._api_key = env(REQUIRED_ENV_VAR)

    def _require_key(self) -> str:
        if not self._api_key:
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable "
                f"{REQUIRED_ENV_VAR} is not set. Set it in a gitignored "
                f"data-router/.env (see router/config.py) and implement the "
                f"real HTTP call — see the module docstring in "
                f"router/adapters/alpha_vantage.py for the extension point. "
                f"No network call has been attempted."
            )
        return self._api_key

    def get_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        self._require_key()
        raise NotImplementedError(
            "Real Alpha Vantage HTTP call not implemented in this sandbox "
            "(no network access). See the extension-point docstring at the "
            "top of this file."
        )

    def get_fundamentals(self, ticker: str) -> list[FundamentalFact]:
        self._require_key()
        raise NotImplementedError("see get_bars docstring")

    def get_corporate_actions(self, ticker: str) -> list[CorporateAction]:
        self._require_key()
        raise NotImplementedError("see get_bars docstring")

    def get_news(self, ticker: Optional[str] = None, since: Optional[date] = None) -> list[NewsItem]:
        self._require_key()
        raise NotImplementedError("see get_bars docstring")

    def get_macro(self, series_id: str, start: date, end: date) -> list[MacroObservation]:
        self._require_key()
        raise NotImplementedError("see get_bars docstring")
