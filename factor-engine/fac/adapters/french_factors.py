"""Kenneth French Data Library adapter — free, no-signup, no API key.

Source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
(the "Fama/French 5 Factors (2x3) [Daily]" and "Momentum Factor (Mom)
[Daily]" rows). Verified live (2026-09, via WebFetch against the page above)
for the exact current download URLs — see `fac.config.FRENCH_5_FACTOR_DAILY_URL`
/ `FRENCH_MOMENTUM_DAILY_URL` — rather than guessed from memory, because this
library's file format has known, documented idiosyncrasies that would silently
corrupt a parser built on a remembered/assumed shape:

  1. Each ZIP contains exactly one CSV. That CSV opens with 1-3 free-text
     BANNER lines (provenance notes, e.g. "This file was created by
     CMPT_ME_BEME_OP_INV_RETS_DAILY using the ... CRSP database." and a note
     about the risk-free rate source) before the real header row. Example,
     copied verbatim from the live 5-factor daily file (confirmed via
     WebFetch against a GitHub mirror of this exact file):

         This file was created by CMPT_ME_BEME_OP_INV_RETS_DAILY using the 201612 CRSP database.,,,,,,
         The 1-month TBill return is from Ibbotson and Associates, Inc.,,,,,
         ,,,,,,
         Date,Mkt-RF,SMB,HML,RMW,CMA,RF
         19630701,-0.67,0,-0.31,0.01,0.15,0.012

  2. Values are PERCENT, not decimal fractions — a `Mkt-RF` cell of `-0.67`
     means -0.67%, i.e. -0.0067 as a return. Every value in every column
     (including RF and Mom) needs `/100` before it is comparable to a
     Tiingo-derived `pct_change()` return. Getting this wrong silently
     produces betas ~100x too small rather than an error — the parser below
     divides unconditionally rather than trying to "detect" percent
     formatting, because there is no reliable signal to detect it FROM other
     than reading the library's own documentation, which states it plainly.

  3. The DAILY files have not been observed to carry a second, differently-
     dated table the way the MONTHLY files do (monthly files append an
     "Annual Factors: January-December" table after a blank line — see
     pandas-datareader's `famafrench.py`, which splits on a double CRLF and
     branches parsing on the resulting chunk's date-column magnitude:
     `> 19000000` => daily/YYYYMMDD, `> 190000` => monthly/YYYYMM, else =>
     annual/YYYY). This sandbox has no outbound network access to fetch and
     inspect a full, current daily file end-to-end to confirm the daily
     files are single-table for certain (see this module's own limitation
     note in factor-engine/README.md) — so rather than assume single-table
     and risk silently absorbing a trailing section if the library ever
     changes this, the parser below defends against BOTH cases the exact
     same way pandas-datareader does: a data row must have an 8-digit
     YYYYMMDD date to be kept. A blank line, a monthly-granularity (6-digit)
     or annual-granularity (4-digit) row, or a trailing copyright/footer
     line, all fail that check and end the table. This is a stricter,
     single mechanism doing the job of both "stop at the blank line" and
     "stop at the annual section" — a monthly/annual row can never masquerade
     as a daily one because its date field is a different width.

This is a self-contained module — this engine shares no code with any other
model in this repo (see graph-engine/README.md: "This engine is its own
world"). There is no "original" Ken French adapter elsewhere in this repo to
copy from (WW-FACTOR is the first engine to use this data source), so this is
the canonical copy other engines should clone from if they ever want French
factors too.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from ..config import (
    FACTOR_COLUMNS,
    FRENCH_5_FACTOR_DAILY_URL,
    FRENCH_CACHE_TTL_SECONDS,
    FRENCH_MOMENTUM_DAILY_URL,
    RF_COLUMN,
    cache_dir,
)

_TIMEOUT = 60
_DAILY_DATE_RE = re.compile(r"^\d{8}$")  # YYYYMMDD — see module docstring, point 3


class FrenchDataError(RuntimeError):
    """Raised when a French Data Library file can't be fetched or doesn't
    parse into the expected shape. Never caught silently anywhere in this
    engine — a broken fetch is a loud failure (see export.py)."""


def _extract_single_csv_text(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise FrenchDataError(
                f"Expected exactly one CSV in the French Data Library zip, found {names!r}."
            )
        # latin-1, not utf-8: these are decades-old plain-ASCII research
        # files; latin-1 is a strict superset of ASCII and never raises a
        # decode error the way utf-8 can on an unexpected stray byte.
        return zf.read(names[0]).decode("latin-1")


def parse_french_daily_csv(text: str, value_columns: list[str]) -> pd.DataFrame:
    """Parse one French Data Library daily CSV's text into a DataFrame
    indexed by date (a `pd.DatetimeIndex`), columns = `value_columns`, values
    already divided by 100 (see module docstring, point 2).

    `value_columns` is the caller's expectation of what the header row
    should contain (order-independent, matched by stripped name) — passed
    explicitly rather than trusted blindly from the file, so a silently
    reordered or renamed column in a future revision of the library raises
    `FrenchDataError` here rather than quietly mislabeling a beta later in
    `regression.py`.
    """
    lines = text.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        first_field = line.split(",", 1)[0].strip()
        if first_field.lower() == "date":
            header_idx = i
            break
    if header_idx is None:
        raise FrenchDataError(
            "Could not find a 'Date' header row in the French CSV — the "
            "library's file format may have changed since this parser was written."
        )

    header = [h.strip() for h in lines[header_idx].split(",")]
    if header[0].lower() != "date":
        raise FrenchDataError(f"Expected the header's first column to be 'Date', got {header[0]!r}.")
    got_value_cols = header[1:]
    missing = [c for c in value_columns if c not in got_value_cols]
    if missing:
        raise FrenchDataError(
            f"French CSV header is missing expected column(s) {missing} — got {header!r}."
        )

    records: dict[pd.Timestamp, dict[str, float]] = {}
    for line in lines[header_idx + 1 :]:
        fields = line.split(",")
        first_field = fields[0].strip()
        if not _DAILY_DATE_RE.match(first_field):
            # Blank line, a monthly/annual-granularity section, or a
            # trailing footer/copyright line — see module docstring point 3.
            # Only stop once we've actually reached the data section; a
            # short banner line that happens not to start with a date is
            # handled above by header_idx, so by construction we are always
            # past the header here.
            break
        if len(fields) != len(header):
            raise FrenchDataError(
                f"Malformed French CSV data row (expected {len(header)} fields, got {len(fields)}): {line!r}"
            )
        d = datetime.strptime(first_field, "%Y%m%d").date()
        row = {}
        for col_name, raw in zip(header[1:], fields[1:]):
            if col_name not in value_columns:
                continue
            row[col_name] = float(raw.strip()) / 100.0
        records[pd.Timestamp(d)] = row

    if not records:
        raise FrenchDataError("French CSV parsed to zero daily data rows.")

    df = pd.DataFrame.from_dict(records, orient="index").sort_index()
    df.index.name = "date"
    return df[value_columns]


def _cache_path(url: str) -> Path:
    name = url.rsplit("/", 1)[-1]
    if name.lower().endswith(".zip"):
        name = name[: -len(".zip")]
    return cache_dir() / f"{name}.csv"


def _cache_is_fresh(path: Path, ttl_seconds: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl_seconds


def _fetch_zip_csv_text(url: str, session: Optional[requests.Session] = None) -> str:
    session = session or requests.Session()
    resp = session.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return _extract_single_csv_text(resp.content)


def _fetch_cached_daily_csv(
    url: str,
    value_columns: list[str],
    *,
    session: Optional[requests.Session] = None,
    force_refresh: bool = False,
    ttl_seconds: float = FRENCH_CACHE_TTL_SECONDS,
) -> pd.DataFrame:
    """Fetch-or-load-from-cache one French daily CSV, then parse it.

    Caches the EXTRACTED CSV TEXT (not the zip) under `fac/data/cache/`, with
    a documented TTL (`fac.config.FRENCH_CACHE_TTL_SECONDS`, default 1 day) —
    Ken French's library updates roughly monthly, so re-downloading on every
    run would just hammer a free, unauthenticated server for no benefit. A
    cache miss or an expired cache re-fetches; `force_refresh=True` always
    re-fetches regardless of age.
    """
    path = _cache_path(url)
    if not force_refresh and _cache_is_fresh(path, ttl_seconds):
        text = path.read_text(encoding="latin-1")
    else:
        text = _fetch_zip_csv_text(url, session=session)
        path.write_text(text, encoding="latin-1")
    return parse_french_daily_csv(text, value_columns)


def fetch_5_factor_daily(
    *, session: Optional[requests.Session] = None, force_refresh: bool = False
) -> pd.DataFrame:
    """Mkt-RF, SMB, HML, RMW, CMA, RF — daily, decimal (already /100)."""
    five_cols = [c for c in FACTOR_COLUMNS if c != "Mom"] + [RF_COLUMN]
    return _fetch_cached_daily_csv(
        FRENCH_5_FACTOR_DAILY_URL, five_cols, session=session, force_refresh=force_refresh
    )


def fetch_momentum_daily(
    *, session: Optional[requests.Session] = None, force_refresh: bool = False
) -> pd.DataFrame:
    """Mom — daily, decimal (already /100)."""
    return _fetch_cached_daily_csv(
        FRENCH_MOMENTUM_DAILY_URL, ["Mom"], session=session, force_refresh=force_refresh
    )


def fetch_factor_panel(
    *, session: Optional[requests.Session] = None, force_refresh: bool = False
) -> pd.DataFrame:
    """The combined daily factor panel this engine's regression consumes:
    columns `fac.config.FACTOR_COLUMNS + [RF_COLUMN]`, indexed by date, one
    row per date covered by BOTH the 5-factor and momentum files (an inner
    join — a date missing from either source is dropped rather than
    forward-filled or interpolated, since a fabricated factor return would
    corrupt every ticker's beta computed against it)."""
    five = fetch_5_factor_daily(session=session, force_refresh=force_refresh)
    mom = fetch_momentum_daily(session=session, force_refresh=force_refresh)
    panel = five.join(mom, how="inner")
    return panel[FACTOR_COLUMNS + [RF_COLUMN]]
