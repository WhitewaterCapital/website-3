"""Financial Modeling Prep earnings-calendar adapter — STUB, same honesty
contract as data-router/router/adapters/alpha_vantage.py: this file makes
ZERO network calls, anywhere, ever. No `import requests`, no `urllib`, no
`httpx`. Every method raises a named error rather than pretending to have
fetched something, because no sandbox available while this was written
(this session's cloud workspace, this session's on-device shell, and the
prior session's identical two sandboxes) has outbound access to FMP,
Tiingo, Alpha Vantage, Finnhub, SEC, or FRED — see PLATFORM_REBUILD_PLAN.md's
Roadblocks for the confirmed evidence (proxy-level policy denial, not a
rate limit).

### To make this real, on your own machine's normal network:

1. Get a free key at https://site.financialmodelingprep.com (dossier-cited,
   "FMP/Finnhub free (limited)" for earnings dates/actuals — verify current
   terms/rate limit before relying on them, per that same dossier's own
   standing advice that provider terms drift).
2. Set `FMP_API_KEY` in a gitignored `earnings-engine/.env`
   (`ee/config.py` already loads it).
3. Implement `get_earnings()` below: FMP's earnings-calendar endpoint takes
   a `from`/`to` date range and returns `{symbol, date, epsEstimated, eps,
   time}` rows (`time` is "bmo"/"amc"/"dmh" — map straight to `session`).
   Filter to `config.UNIVERSE` client-side (the free tier's calendar
   endpoint returns the whole market, not per-symbol).
4. FALLBACK, if FMP's calendar endpoint turns out gated on the free tier
   (unverified — see above): Nasdaq's public earnings page
   (https://www.nasdaq.com/market-activity/earnings) was confirmed live and
   loading real data this session via a browser on a normal connection —
   16 real entries for the week of 2026-09-14 — but it's an HTML page, not
   an API, so this would be a scrape (respect robots.txt / rate yourself)
   rather than the clean adapter call FMP offers. Try FMP first.
5. Nothing else changes — export.py only calls `get_earnings()` and only
   ever sees the plain dict shape `synthetic.py` already returns for the
   demo path; it has no idea whether the real values came from an HTTP
   call or a fixture.
"""

from __future__ import annotations

from datetime import date

from ..config import env, EARNINGS_CALENDAR_API_KEY_VAR


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without FMP_API_KEY set. Named
    after the missing env var so the fix is obvious from the message alone
    — same convention as data-router's identical exception."""


class FmpCalendarAdapter:
    name = "financial-modeling-prep"

    def __init__(self) -> None:
        self._api_key = env(EARNINGS_CALENDAR_API_KEY_VAR)

    def _require_key(self) -> str:
        if not self._api_key:
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable "
                f"{EARNINGS_CALENDAR_API_KEY_VAR} is not set. Set it in a "
                f"gitignored earnings-engine/.env. No network call has been "
                f"attempted. See the extension-point docstring at the top "
                f"of adapters/fmp_calendar.py."
            )
        return self._api_key

    def get_earnings(self, universe: list[str], start: date, end: date) -> list[dict]:
        self._require_key()
        raise NotImplementedError(
            "Real FMP earnings-calendar HTTP call not implemented in any "
            "sandbox this repo has been built in (no network access). See "
            "the extension-point docstring at the top of this file for the "
            "exact endpoint shape and the Nasdaq-page fallback."
        )
