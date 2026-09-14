"""Alpha Vantage analyst-estimates adapter — STUB, same honesty contract as
adapters/fmp_calendar.py: this file makes ZERO network calls, anywhere,
ever. No `import requests`, no `urllib`, no `httpx`. Every method raises a
named error rather than pretending to have fetched something, because — as
of this module being written (2026-09-14) — no sandbox available to build
this (this session's cloud container, whose proxy returned 403
connect_rejected/"organization policy" for site.financialmodelingprep.com,
finnhub.io, www.alphavantage.co, and data.nasdaq.com; and this session's
on-device shell on the repo owner's own Mac, which returned curl exit 56/
connection-refused for the same hosts) has outbound access to any of the
providers checked. See PLATFORM_REBUILD_PLAN.md's Roadblocks for the same
wall documented against Tiingo/Alpha Vantage/iShares/FMP by a prior
session — this is the same wall again, re-confirmed, not a new one.

### WHY ALPHA VANTAGE, AND WHY THIS IS THE ONE TIER-B PATH THIS ENGINE
### SHIPS WIRED, PER THE 2026-09-14 PROVIDER SURVEY:

The platform's research dossier (research/equity-model-research-dossier.md,
line ~397) flags analyst estimates/revisions as "Poor free coverage" and
names I/B/E/S (WRDS), Zacks, FactSet as the usual paid sources. This
session re-checked that verdict against current (2026) terms for every
free-tier candidate a small unfunded team could actually use, since a
research dossier's own standing advice ("verify current terms — provider
terms drift") demands that be re-checked periodically rather than taken as
permanently settled:

- **Financial Modeling Prep** (already this engine's calendar vendor) —
  CONFIRMED PAID for estimates. Fetched site.financialmodelingprep.com/
  pricing-plans directly (twice, consistent both times): the "Analyst"
  feature row shows a dash (not included) for Basic/Free, Starter, AND
  Premium tiers — only "Ultimate" shows an "L A" (limited-access)
  designation. The FMP_API_KEY this engine already uses for the calendar
  (adapters/fmp_calendar.py) does NOT unlock estimates on the free tier;
  they are a materially higher-tier product from the same vendor.
- **Finnhub** — INCONCLUSIVE, not usable as-is. finnhub.io's docs/pricing
  pages are a client-rendered SPA that returned only HTML `<meta>` tags to
  every fetch attempt this session made (confirmed repeatedly, not a one-
  off) — this session could not read the actual endpoint-level Premium
  badges Finnhub shows in its rendered docs. Third-party sources
  disagreed: apicostcalc.com's free-tier summary lists "basic fundamentals"
  as included free; tradingdatacompare.com's 2026 review describes a newer,
  simpler two-tier structure ("Free: 60 calls/min, real-time quotes,
  WebSocket trades" vs "All-In-One $50/mo: premium datasets, financials")
  that reads as fundamentals/estimates now being paid-only. A 2020 GitHub
  issue (finnhubio/Finnhub-API#271) documents Finnhub moving previously-
  free endpoints (Dividends, Major Developments) to Premium before, i.e.
  this vendor has a track record of tightening the free tier over time.
  Net: not confirmed free, not confirmed paid — do not build against it
  without a session that can actually load finnhub.io's JS-rendered docs
  or a live key to test with.
- **Alpha Vantage** — the one CONFIRMED-workable free path, evidenced (not
  a live authenticated fetch — see below) via:
    1. macroption.com/alpha-vantage-earnings-calendar (a long-standing,
       field-level-accurate third-party AV reference) documents the
       EARNINGS_CALENDAR function's output columns verbatim: `symbol,
       name, reportDate, fiscalDateEnding, estimate, currency` — `estimate`
       is explicitly described as "Earnings per share (EPS) estimated by
       analysts covering the stock." No premium/paid notice anywhere on
       that page, unlike Alpha Vantage's own docs page convention of
       flagging premium-only functions explicitly.
    2. A live, unauthenticated URL surfaced directly in search results —
       https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=demo
       — is Alpha Vantage's own public demo link for this exact function,
       which vendors do not typically publish for premium-gated endpoints.
    3. Independent tutorials (mbosse.medium.com "AlphaVantage API for
       Earnings Data"; dm13450.github.io's AlphaVantage.jl fundamentals
       post) both show real example output from the plain EARNINGS
       function (distinct from EARNINGS_CALENDAR) containing
       `estimatedEPS`, `surprise`, and `surprisePercentage` per historical
       quarter, obtained with, in their words, just "your free API key" —
       neither mentions hitting a paywall.
    NOT verified: an actual authenticated HTTP round-trip from this
    session (blocked, see above — the public `apikey=demo` link only
    serves symbol=IBM and a fixed function allowlist, and did not return
    body content through this session's fetch tooling either). Treat the
    free-tier claim above as well-evidenced-but-not-live-fetch-confirmed,
    and re-verify with a real key before depending on it for anything
    beyond this engine's own honest-abstention default.
- **Zacks** — near-certainly paid, as the dossier already assumed. Not
  independently re-verified beyond noticing Zacks' own Nasdaq Data Link
  listing (data.nasdaq.com/databases/ZEE, "Zacks Earnings Estimates") is a
  commercial database with no free tier advertised anywhere this session
  could find, and Zacks' own site sells a separate paid "Zacks Data API."
  Not worth more research time given how consistently every independent
  source treats Zacks data as commercial.
- **Nasdaq Data Link / Quandl** — data.nasdaq.com is itself a client-
  rendered SPA (same problem as Finnhub); this session could not load its
  dataset-search results to confirm or deny a free consensus-estimates
  dataset exists. The one dataset this session DID identify by name (ZEE,
  Zacks Earnings Estimates) is Zacks-sourced and, per the point above,
  almost certainly paid. No free alternative dataset was found.

### To make this real, on a machine with normal network access:

1. Get a free key at https://www.alphavantage.co/support/#api-key.
2. Set `ALPHA_VANTAGE_API_KEY` in a gitignored `earnings-engine/.env`
   (`ee/config.py` already loads it via the same `env()` helper FMP uses).
3. Implement `get_estimate_inputs()` below as TWO calls per ticker:
   a. `GET https://www.alphavantage.co/query?function=EARNINGS_CALENDAR
      &symbol=<TICKER>&horizon=3month&apikey=<KEY>` — a CSV (not JSON)
      response with columns `symbol,name,reportDate,fiscalDateEnding,
      estimate,currency`. `estimate` is the forward consensus EPS for the
      next unreported print — this is `eps_estimate`.
   b. `GET https://www.alphavantage.co/query?function=EARNINGS
      &symbol=<TICKER>&apikey=<KEY>` — JSON with a `quarterlyEarnings`
      list of trailing quarters, each `{reportedDate, reportedEPS,
      estimatedEPS, surprise, surprisePercentage, ...}`. Take the trailing
      `ee.sue.MIN_SURPRISE_QUARTERS_FOR_STDEV`-or-more quarters' `surprise`
      values (already `reportedEPS - estimatedEPS`, per AV's own field
      semantics — do not recompute it from the two EPS fields, since
      AV's own `surprise` is the audited value) and pass them to
      `ee.sue.estimate_stdev_from_surprises()`.
4. Rate limits: Alpha Vantage's free key is 25 requests/day (per the
   platform-wide convention of checking a vendor's OWN current docs before
   relying on a remembered number — this session could not re-verify that
   exact figure live; confirm it before wiring this into a scheduled job,
   since two calls per ticker across a 6-name universe is only 12
   calls/run but a naive daily cron could still exceed a very low quota).
5. Nothing else changes — export.py only calls `get_estimate_inputs()` per
   ticker and handles VendorNotConfiguredError/NotImplementedError exactly
   like it already handles the FMP calendar adapter's stub state.
"""

from __future__ import annotations


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without ALPHA_VANTAGE_API_KEY
    set. Named after the missing env var so the fix is obvious from the
    message alone — same convention as fmp_calendar.py's identical
    exception and data-router's original."""


class AlphaVantageEstimatesAdapter:
    name = "alpha-vantage"

    def __init__(self) -> None:
        # Imported lazily (module-level, not function-level) purely to
        # keep this file's only dependency on the rest of the engine
        # explicit and minimal — mirrors fmp_calendar.py's import shape.
        from ..config import env, EARNINGS_ESTIMATES_API_KEY_VAR

        self._api_key = env(EARNINGS_ESTIMATES_API_KEY_VAR)
        self._key_var = EARNINGS_ESTIMATES_API_KEY_VAR

    def _require_key(self) -> str:
        if not self._api_key:
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable "
                f"{self._key_var} is not set. Set it in a gitignored "
                f"earnings-engine/.env. No network call has been "
                f"attempted. See the extension-point docstring at the top "
                f"of adapters/alpha_vantage_estimates.py."
            )
        return self._api_key

    def get_estimate_inputs(self, ticker: str) -> dict:
        """Would return `{"eps_estimate": float | None,
        "eps_estimate_stdev": float | None, "estimate_source": str}` for
        one ticker. Raises NotImplementedError until a network-capable
        session wires in the two real HTTP calls described in this
        module's docstring — see there for the exact endpoint shapes."""
        self._require_key()
        raise NotImplementedError(
            "Real Alpha Vantage EARNINGS_CALENDAR / EARNINGS HTTP calls "
            "not implemented in any sandbox this repo has been built in "
            "(no outbound network access — see the extension-point "
            "docstring at the top of this file for exactly what to "
            "implement and the evidence for why Alpha Vantage is the "
            "right vendor to implement it against)."
        )
