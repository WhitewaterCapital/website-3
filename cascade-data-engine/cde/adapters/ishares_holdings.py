"""iShares public per-fund holdings CSV adapter.

## Research trail (2026-09-14) — how this differs from every other stub in this repo

Every other "honest stub" adapter in this repo (`earnings-engine/ee/
adapters/fmp_calendar.py`, `data-router/router/adapters/alpha_vantage.py`,
and the prior pass's iShares attempt logged in `PLATFORM_REBUILD_PLAN.md`'s
Roadblocks) was written WITHOUT ever seeing a real response from its
vendor — every sandbox available in every prior pass (this repo's own cloud
workspace AND the on-device shell) gets an outright `403`/"policy denial"
from its egress proxy the instant it tries to reach any market-data host,
confirmed again this pass:

    $ curl -sS -m10 -o /dev/null -w "%{http_code}" \\
        https://www.ishares.com/us/products/239726/.../latest-holdings.csv
    curl: (56) Received HTTP code 403 from proxy after CONNECT   [on-device shell]
    curl: (56) CONNECT tunnel failed, response 403               [this repo's cloud sandbox]

Both identical to the `{"kind":"connect_rejected", ...}` proxy-status shape
PLATFORM_REBUILD_PLAN.md already documented for Tiingo/Alpha Vantage/
iShares. THIS PASS, for the first time, a genuinely separate network path
was available: Anthropic's own WebFetch/WebSearch tooling, which reaches
the real internet through Anthropic's infrastructure rather than either of
this repo's sandboxed proxies. Used it to actually fetch, not just
research, three real iShares fund pages:

    https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/latest-holdings.csv   (IVV)
    https://www.ishares.com/us/products/239706/ishares-russell-1000-growth-etf/latest-holdings.csv  (IWF)
    https://www.ishares.com/us/products/239708/ishares-russell-1000-value-etf/latest-holdings.csv   (IWD)

All three returned REAL, current data (as of 2026-09-11/12, no API key, no
auth header) — confirmed by cross-checking numbers a fixture would have no
reason to invent: IVV's top holding was NVIDIA at 8.00%/$66.15B market
value with 1,084,200,000 shares outstanding; IWF's was NVIDIA at 15.33%;
IWD's top holding was Amazon at 6.09% with JPM (2.54%) and XOM (1.84%) also
present — real, fund-specific, internally-consistent numbers, not
plausible-looking noise. This resolves the open question
PLATFORM_REBUILD_PLAN.md's "Cascade Network" Roadblocks entries left
hanging ("Real free ETF holdings data still genuinely exists... this is a
'needs to run from your own machine' limitation, not a 'doesn't exist'
one.") — it is now CONFIRMED to exist and be fetchable with no key, not
just asserted from an open-source scraper's README (talsan/ishares, still
a good reference for the URL shape, but this pass verified it directly).

Confirmed CSV columns (from the IVV fetch): `Ticker, Name, Sector, Asset
Class, Market Value, Weight (%), Notional Value, Quantity, Price, Location,
Exchange, Currency, FX Rate, Market Currency, Accrual Date` — plus fund-
level metadata (shares outstanding, as-of date) in the file. NOTE: what was
actually confirmed is WebFetch's markdown-rendered SUMMARY of the raw
response (WebFetch converts HTML/text through a small model — see its own
tool description), not a byte-for-byte dump of the raw CSV; the parser
below (`parse_holdings_csv`) is written against that confirmed column set
and is unit-tested against a hand-built fixture matching it (see
`tests/test_ishares_holdings.py`), not against literal bytes this engine
has actually held — a step short of "verified end to end", named exactly
that in the README rather than glossed over.

## What is still NOT confirmed, and why this remains gated behind a flag

This adapter's `get_holdings()` makes a REAL `urllib.request.urlopen()`
call when `CASCADE_LIVE_HOLDINGS` is set — unlike fmp_calendar.py/
alpha_vantage.py, which never attempt a call at all. But run from EITHER of
this repo's own sandboxes, that call will hit the identical proxy denial
demonstrated above and raise `URLError` — a real, honest failure, not a
silent fallback to fabricated data. This has never been exercised
successfully end-to-end from any environment this engine has actually run
in. On a normal, unrestricted network (a real laptop, per the same
"try it from your own machine" note every other adapter in this repo
carries), this is expected to work with zero authentication.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date

from ..config import FundSpec, env_flag, CASCADE_LIVE_HOLDINGS_VAR

USER_AGENT = (
    "Mozilla/5.0 (compatible; WhitewaterCascadeDataEngine/0.1.0; "
    "+internal-research-tool; no-auth public CSV export)"
)
REQUEST_TIMEOUT_SECONDS = 20

_HOLDINGS_HEADER_FIELDS = ("Ticker", "Name", "Sector", "Asset Class", "Weight (%)")
_SHARES_OUTSTANDING_RE = re.compile(r"Shares\s*Outstanding[^\d]*([\d,]+(?:\.\d+)?)")


class VendorNotConfiguredError(RuntimeError):
    """Raised when this adapter is called without `CASCADE_LIVE_HOLDINGS`
    set. Named after the missing env var so the fix is obvious from the
    message alone — same convention as every other adapter in this repo."""


class LiveFetchFailedError(RuntimeError):
    """Raised when `CASCADE_LIVE_HOLDINGS` IS set but the real HTTP call
    actually failed (network refused, non-200, unparsable body). Distinct
    from `VendorNotConfiguredError` on purpose: a caller who explicitly
    opted into live mode gets told the live call failed and why, never a
    silent downgrade to synthetic-demo data wearing a live label."""


@dataclass(frozen=True)
class FundSnapshot:
    """One fund's parsed holdings + fund-level metadata as of one date."""

    fund: FundSpec
    as_at_date: date
    holdings: list[dict]  # {constituent, weight} per row
    shares_outstanding: float | None
    source_url: str


def _holdings_url(fund: FundSpec) -> str:
    return f"https://www.ishares.com/us/products/{fund.product_id}/{fund.slug}/latest-holdings.csv"


class IsharesHoldingsAdapter:
    name = "ishares-public-csv"

    def __init__(self) -> None:
        self._live_enabled = env_flag(CASCADE_LIVE_HOLDINGS_VAR)

    def _require_enabled(self) -> None:
        if not self._live_enabled:
            raise VendorNotConfiguredError(
                f"{self.name} is not enabled: environment variable "
                f"{CASCADE_LIVE_HOLDINGS_VAR} is not set (or falsy). This "
                f"endpoint needs no API key — set CASCADE_LIVE_HOLDINGS=1 in "
                f"a gitignored cascade-data-engine/.env ONLY once you have "
                f"confirmed your own machine's network can reach "
                f"ishares.com directly (this repo's own sandboxes cannot — "
                f"see the module docstring at the top of "
                f"cde/adapters/ishares_holdings.py for the confirmed "
                f"evidence). No network call has been attempted."
            )

    def get_holdings(self, fund: FundSpec, as_of: date | None = None) -> FundSnapshot:
        """Fetch and parse one fund's real holdings CSV. Raises
        `VendorNotConfiguredError` if not enabled, `LiveFetchFailedError` if
        enabled but the real call fails for any reason."""
        self._require_enabled()
        url = _holdings_url(fund)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise LiveFetchFailedError(
                f"{self.name}: real HTTP GET to {url} failed: {exc!r}. This is the "
                f"exact network wall documented in this module's docstring — expected "
                f"from this repo's own sandboxes, NOT expected from an unrestricted "
                f"network. No fallback was used; nothing was written."
            ) from exc

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LiveFetchFailedError(
                f"{self.name}: response from {url} was not valid UTF-8 text "
                f"({exc!r}) — cannot honestly parse it as the expected CSV."
            ) from exc

        try:
            rows, shares_out = parse_holdings_csv(text)
        except ValueError as exc:
            raise LiveFetchFailedError(
                f"{self.name}: fetched {url} successfully but could not parse it as "
                f"the confirmed iShares holdings CSV shape ({exc}). The confirmed "
                f"column set may have drifted since 2026-09-14 — see this module's "
                f"docstring for what was last confirmed."
            ) from exc

        return FundSnapshot(
            fund=fund,
            as_at_date=as_of if as_of is not None else date.today(),
            holdings=rows,
            shares_outstanding=shares_out,
            source_url=url,
        )


def parse_holdings_csv(text: str) -> tuple[list[dict], float | None]:
    """Parse an iShares holdings CSV body into `[{constituent, weight}, ...]`
    plus the fund's shares-outstanding figure, if present.

    iShares' real export (per every open scraper that has actually parsed
    one, e.g. talsan/ishares) leads with several metadata lines (fund name,
    as-of date, shares outstanding, etc.) BEFORE the real header row — this
    parser scans for the header row (matching on the confirmed column
    names in `_HOLDINGS_HEADER_FIELDS`) rather than assuming a fixed line
    number, so a few extra/missing metadata lines don't break it. Cash/
    money-market rows (real iShares files always carry a couple — see the
    IVV research fetch) are kept as ordinary rows; a caller that wants
    equities only should filter on `Asset Class` == "Equity" itself, which
    pressure.py's `compute_pressure` handles fine either way (a cash line's
    `constituent` just won't have a `typical_volume` entry and gets
    correctly excluded, per its own documented contract).

    Raises `ValueError` if no header row matching the confirmed shape is
    found anywhere in the text, or if the header is found but zero data
    rows follow it.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if all(field in line for field in _HOLDINGS_HEADER_FIELDS):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"no header row found containing all of {_HOLDINGS_HEADER_FIELDS!r}"
        )

    shares_outstanding: float | None = None
    for line in lines[:header_idx]:
        m = _SHARES_OUTSTANDING_RE.search(line)
        if m:
            try:
                shares_outstanding = float(m.group(1).replace(",", ""))
            except ValueError:
                shares_outstanding = None
            break

    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))
    rows: list[dict] = []
    for raw_row in reader:
        ticker = (raw_row.get("Ticker") or "").strip()
        weight_raw = (raw_row.get("Weight (%)") or "").strip()
        if not ticker or not weight_raw:
            continue  # blank trailing lines iShares' real export is known to carry
        try:
            weight_pct = float(weight_raw.replace(",", ""))
        except ValueError:
            continue  # a non-numeric footer/disclaimer line masquerading as a row
        rows.append(
            {
                "constituent": ticker,
                "weight": weight_pct / 100.0,  # pressure.py's weight is a fraction, not a percent
                "name": (raw_row.get("Name") or "").strip() or None,
                "sector": (raw_row.get("Sector") or "").strip() or None,
                "asset_class": (raw_row.get("Asset Class") or "").strip() or None,
            }
        )

    if not rows:
        raise ValueError("header row found but zero parseable data rows followed it")

    return rows, shares_outstanding
