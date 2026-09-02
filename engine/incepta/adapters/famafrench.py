"""Kenneth R. French Data Library adapter (free, no API key).

Downloads the daily Fama-French 5 factors + the daily Momentum factor from the
Dartmouth library and returns one aligned DataFrame of DAILY factor returns in
decimal (the source is in percent; we divide by 100).

Columns: mkt_rf, smb, hml, rmw, cma, rf, mom   (index = date)

Verified free source (2026-08):
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
This is the standard academic factor-return source and is enough for v1 risk
decomposition (dossier §6/§9).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pandas as pd
import requests

from .. import config

_FF5_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
)
_MOM_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_daily_CSV.zip"
)
_TIMEOUT = 60
_DATE_ROW = re.compile(r"^\s*(\d{8})\s*,")


def _download_zip_csv(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": "incepta-research/0.1"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    name = zf.namelist()[0]
    return zf.read(name).decode("latin-1")


def _parse_factor_csv(text: str, colnames: list[str]) -> pd.DataFrame:
    """Parse a Ken French daily CSV: skip preamble, keep only YYYYMMDD data rows
    (the daily files have a single daily block, then annual blocks appear only in
    monthly files — daily files are single-block, so date-row filtering suffices).
    """
    records = []
    for line in text.splitlines():
        m = _DATE_ROW.match(line)
        if not m:
            continue
        parts = [p.strip() for p in line.split(",")]
        d = pd.to_datetime(parts[0], format="%Y%m%d").date()
        vals = []
        ok = True
        for p in parts[1:]:
            try:
                vals.append(float(p) / 100.0)  # percent -> decimal
            except ValueError:
                ok = False
                break
        if ok and len(vals) >= len(colnames):
            records.append((d, *vals[: len(colnames)]))
    df = pd.DataFrame(records, columns=["date", *colnames]).set_index("date")
    return df


def fetch_factors(use_cache: bool = True) -> pd.DataFrame:
    cache = config.data_dir() / "ff_factors_daily.pkl"
    if use_cache and cache.exists():
        return pd.read_pickle(cache)

    ff5 = _parse_factor_csv(
        _download_zip_csv(_FF5_URL), ["mkt_rf", "smb", "hml", "rmw", "cma", "rf"]
    )
    mom = _parse_factor_csv(_download_zip_csv(_MOM_URL), ["mom"])
    out = ff5.join(mom, how="inner").sort_index()
    try:
        out.to_pickle(cache)
    except Exception:  # pragma: no cover
        pass
    return out
