"""iShares public fund-overview-page NAV-per-share adapter.

## Why this file exists

`cascade-data-engine/README.md`'s "still open" section documented that NAV
per share is not present in the iShares holdings CSV
(`adapters/ishares_holdings.py`) at all, and that `quant-infra/cascade/
pressure.py`'s `estimate_flow_from_shares_outstanding` (and, separately,
`estimate_flow_proxy`) need a NAV to price a shares-outstanding delta (or a
premium/discount) into dollars — the README named this as "iShares' own
product page does show NAV ... it just isn't in the holdings CSV, so this
is a second fetch to add, not designed here." This module is that second
fetch.

## Research trail (2026-09-14) — genuinely weaker confirmation than the CSV

Fetched the fund OVERVIEW page (not the `/latest-holdings.csv` endpoint —
a different URL, same `ishares.com` host, same no-auth public page) via
WebFetch, a separate network path from this repo's own sandboxed shells
(see `ishares_holdings.py`'s module docstring for why that distinction
matters — the same proxy wall blocks this host from every sandbox this
engine has run in):

    https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf

CONFIRMED present, twice, independently: a current NAV-per-share figure
displayed in the page's key-fund-information area, phrased as
"NAV as of Sep 11, 2026 $768.0252" (IVV, fetched 2026-09-14). Both fetches
agreed on the number and the surrounding phrase. They did NOT agree on
structure: one WebFetch pass reported the figure as living inside a
`<script type="application/ld+json">` block with keys resembling
`netAssetValue`/`unitText`/`asOfDate`; a second, more careful pass over the
SAME url found no such script block at all and described the figure as
plain HTML text with no structured JSON backing it. This is a genuinely
real disagreement, not glossed over here — WebFetch renders pages through
a small model's markdown summary of the content, not raw bytes (the exact
same caveat `ishares_holdings.py`'s own docstring names for why its CSV
column-name confirmation, though itself real, is not a byte-for-byte
dump). Given the disagreement, this adapter does NOT assume a JSON-LD
shape it cannot verify. It treats the page as opaque HTML text: strips
tags naively and regex-matches the literal confirmed phrase pattern
"NAV as of <date> $<number>" against the detagged text. This is a real,
named-lower-confidence parse than the holdings CSV's column-header check
(that one only needs the same field NAMES to reappear; this one depends on
an exact English phrase surviving a markup redesign) — flagged here, not
smoothed over. If iShares ever rephrases that label, `parse_nav_from_html`
raises `ValueError` (wrapped into `LiveFetchFailedError` by `get_nav`)
rather than silently returning a stale or wrong number.

**No separate no-auth JSON/CSV endpoint carrying NAV alone was found.**
Both WebFetch passes over the overview page, and inspection of the
holdings-CSV endpoint's own raw text (see `ishares_holdings.py`), turned up
no dedicated "fundamentals"/"quote" API — this is exactly a second HTML
page fetch, not a second structured export, which is the honest limit of
what this pass could confirm free/no-auth.

## Gate

Same `CASCADE_LIVE_HOLDINGS` flag as `ishares_holdings.py` — this is the
same host (`ishares.com`), same no-key public page, so there is nothing
separate to gate on. Never exercised successfully end to end from any
sandbox this engine has run in, for the identical proxy-wall reason
documented throughout this engine (try it from an unrestricted network).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date

from ..config import CASCADE_LIVE_HOLDINGS_VAR, FundSpec, env_flag

USER_AGENT = (
    "Mozilla/5.0 (compatible; WhitewaterCascadeDataEngine/0.1.0; "
    "+internal-research-tool; no-auth public fund page)"
)
REQUEST_TIMEOUT_SECONDS = 20

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# The exact confirmed phrase shape: "NAV as of <Month DD, YYYY> ... $<number>".
# Tolerant of a few non-digit characters (currency symbols, a stray "$$"
# rendering artifact seen in one WebFetch pass, whitespace) between the date
# and the number, since the raw byte-level markup was never actually held —
# see module docstring.
_NAV_RE = re.compile(
    r"NAV\s*as\s*of\s*([A-Za-z]+\s+\d{1,2},?\s*\d{4})[^0-9]{0,30}?([\d,]+\.\d+)",
    re.IGNORECASE,
)


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without `CASCADE_LIVE_HOLDINGS`
    set. Same convention as every other adapter in this repo."""


class LiveFetchFailedError(RuntimeError):
    """Raised when `CASCADE_LIVE_HOLDINGS` IS set but the real HTTP call or
    the subsequent parse actually failed. Distinct from
    `VendorNotConfiguredError` on purpose — a caller who explicitly opted
    into live mode gets told the live call failed and why, never a silent
    downgrade to a fabricated NAV."""


@dataclass(frozen=True)
class NavSnapshot:
    """One fund's parsed NAV-per-share as of one date."""

    fund: FundSpec
    as_at_date: date
    nav_per_share: float
    nav_as_of_label: str  # the raw "as of" date text the page itself showed, for audit
    source_url: str


def _overview_url(fund: FundSpec) -> str:
    return f"https://www.ishares.com/us/products/{fund.product_id}/{fund.slug}"


def parse_nav_from_html(html: str) -> tuple[float, str]:
    """Detag `html` naively and regex-match the confirmed "NAV as of <date>
    $<number>" phrase. Raises `ValueError` if the phrase isn't found or the
    matched number isn't parseable — never returns a guessed value."""
    detagged = _WS_RE.sub(" ", _TAG_RE.sub(" ", html))
    m = _NAV_RE.search(detagged)
    if not m:
        raise ValueError(
            "no 'NAV as of <date> $<number>' phrase found in the detagged page text — "
            "the confirmed phrase shape may have drifted since 2026-09-14; see this "
            "module's docstring for what was last confirmed"
        )
    label, num = m.group(1), m.group(2)
    try:
        value = float(num.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"matched NAV text {num!r} was not parseable as a float") from exc
    return value, label


class IsharesNavAdapter:
    """Real adapter against iShares' public fund overview page — makes a
    genuine `urllib` GET when `CASCADE_LIVE_HOLDINGS` is set. See this
    module's docstring for the full research trail and the specific
    lower-confidence parsing caveat vs. the holdings CSV."""

    name = "ishares-fund-overview-page"

    def __init__(self) -> None:
        self._live_enabled = env_flag(CASCADE_LIVE_HOLDINGS_VAR)

    def _require_enabled(self) -> None:
        if not self._live_enabled:
            raise VendorNotConfiguredError(
                f"{self.name} is not enabled: environment variable "
                f"{CASCADE_LIVE_HOLDINGS_VAR} is not set (or falsy). This is the same "
                f"host and gate as ishares_holdings.py — see that module's docstring, "
                f"and this module's own docstring, for the confirmed evidence. No "
                f"network call has been attempted."
            )

    def get_nav(self, fund: FundSpec, as_of: date | None = None) -> NavSnapshot:
        """Fetch and parse one fund's real NAV-per-share. Raises
        `VendorNotConfiguredError` if not enabled, `LiveFetchFailedError` if
        enabled but the real call or the parse fails for any reason."""
        self._require_enabled()
        url = _overview_url(fund)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise LiveFetchFailedError(
                f"{self.name}: real HTTP GET to {url} failed: {exc!r}. This is the exact "
                f"network wall documented in this module's docstring — expected from "
                f"this repo's own sandboxes, NOT expected from an unrestricted network. "
                f"No fallback was used; nothing was written."
            ) from exc

        try:
            text = raw.decode("utf-8", errors="replace")
        except UnicodeDecodeError as exc:  # pragma: no cover - errors="replace" never raises
            raise LiveFetchFailedError(
                f"{self.name}: response from {url} could not be decoded as text ({exc!r})."
            ) from exc

        try:
            nav_per_share, label = parse_nav_from_html(text)
        except ValueError as exc:
            raise LiveFetchFailedError(
                f"{self.name}: fetched {url} successfully but could not parse a NAV "
                f"figure from it ({exc}). See this module's docstring for the specific "
                f"lower-confidence-than-the-CSV caveat this parser carries."
            ) from exc

        return NavSnapshot(
            fund=fund,
            as_at_date=as_of if as_of is not None else date.today(),
            nav_per_share=nav_per_share,
            nav_as_of_label=label,
            source_url=url,
        )
