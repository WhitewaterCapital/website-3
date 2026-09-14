"""Central configuration for WW-CASCADE-DATA — the real-holdings ingestion
engine that feeds `quant-infra/cascade/pressure.py`.

Mirrors the discipline of `earnings-engine/ee/config.py`: one place for
every tunable constant, a gitignored per-engine `.env` loaded without a
third-party dependency, and a fixed live-vs-synthetic gate on one named
env var (see `export.py`).

## Why this engine's gate is a FLAG, not an API key

Every other engine in this repo (WW-Earnings/FMP, data-router/Alpha
Vantage, factor-engine/graph-engine/Tiingo) gates on the PRESENCE of a
vendor API key, because their vendors require one. iShares' public
per-fund holdings CSV export (see `adapters/ishares_holdings.py` for the
full research trail) needs no key at all — it is a plain, unauthenticated
GET. There is nothing to check for "configured" in the usual sense, so the
gate here is instead an explicit opt-in boolean, `CASCADE_LIVE_HOLDINGS`,
that a human sets only once they've confirmed THEIR OWN machine's network
can actually reach ishares.com (this repo's own sandboxes cannot — see the
adapter's module docstring and PLATFORM_REBUILD_PLAN.md's Roadblocks for
the confirmed evidence). Requiring an explicit flag rather than "just try
it and see" keeps the same contract as every other engine: an unconfigured
environment always gets the honest synthetic-demo fallback, never a code
path that silently attempts (and fails) a real network call nobody asked
for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Duplicated (not imported) from the identical
    loader in earnings-engine/factor-engine/weekly-engine — this engine is
    sealed, same convention as every other engine in this repo."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def env_flag(name: str) -> bool:
    v = env(name)
    if v is None:
        return False
    return v.lower() not in ("0", "false", "no", "off", "")


# --- Live-data gate ----------------------------------------------------------
# See the module docstring above for why this is a boolean flag rather than
# an API-key presence check. Checked in export.py exactly the way every
# other engine here gates on its own vendor key.
CASCADE_LIVE_HOLDINGS_VAR = "CASCADE_LIVE_HOLDINGS"


@dataclass(frozen=True)
class FundSpec:
    """One iShares fund this engine tracks. `product_id` and `slug` are the
    two path segments iShares' own site uses to address a fund — both
    confirmed live (via WebFetch, from outside this repo's own blocked
    sandboxes — see the adapter docstring) on 2026-09-14 by fetching each
    fund's `latest-holdings.csv` and reading back real current top-10
    holdings and shares-outstanding figures. Ticker is WhitewaterPlatform's
    own label for the fund, not something iShares' file provides directly."""

    ticker: str
    product_id: str
    slug: str
    name: str


# Starter universe: three large, liquid iShares Russell-family funds chosen
# specifically because their constituents overlap heavily (each is a cut of
# the same large-cap US equity market: full-market IVV, growth-tilted IWF,
# value-tilted IWD) — this is exactly the shape `pressure.py`'s own test
# suite exercises ("a name in many funds must have its pressure correctly
# SUMMED across all of them"), confirmed for real this session: AAPL and
# MSFT sit in all three funds' actual top-10 (different weights in each),
# and IWD's top-10 alone includes JPM and XOM, both of which also sit in
# IVV (S&P 500) and are part of this platform's own existing default
# cross-sectional UNIVERSE (see earnings-engine/ee/config.py, factor-engine,
# etc.) — a deliberate, real point of continuity with the rest of the repo,
# not a coincidence.
FUNDS: tuple[FundSpec, ...] = (
    FundSpec("IVV", "239726", "ishares-core-sp-500-etf", "iShares Core S&P 500 ETF"),
    FundSpec("IWF", "239706", "ishares-russell-1000-growth-etf", "iShares Russell 1000 Growth ETF"),
    FundSpec("IWD", "239708", "ishares-russell-1000-value-etf", "iShares Russell 1000 Value ETF"),
)

# Same fixed 6-name cross-sectional universe every other screen in this repo
# uses (see earnings-engine/ee/config.py's identical comment) — used ONLY
# as the constituent basket for the synthetic-demo fallback below, so a
# reader unfamiliar with the real funds' actual holdings still sees names
# they recognize from the rest of the platform. Duplicated, not imported —
# this engine is sealed, same convention as every engine in this repo.
SYNTHETIC_CONSTITUENTS: list[str] = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"]

SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "0.1.0"

DISCLAIMER = (
    "Mechanical flow-pressure estimate per quant-infra/cascade/pressure.py's "
    "documented functional form (pressure = sum over funds holding a name of "
    "weight * fund_flow / typical_daily_dollar_volume). Two inputs are "
    "structurally incomplete as shipped, and pressure is honestly NaN "
    "wherever they are: (1) fund flow needs a SECOND day's shares-outstanding "
    "reading to diff against (see state/fund_snapshots.jsonl) — a single run "
    "never has one; (2) typical_volume per constituent is not sourced at all "
    "in this pass (this platform's own volume source, Tiingo, is blocked "
    "from every sandbox this engine has been built in exactly like the "
    "holdings feed itself — see cde/adapters/ishares_holdings.py's module "
    "docstring). This is honest abstention, not a bug: see the "
    "skipped_products/warnings fields on every export for exactly which "
    "constituent-legs were excluded and why, per pressure.py's own contract."
)


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # cascade-data-engine/cde/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir() -> Path:
    d = engine_root() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fund_snapshots_path() -> Path:
    return state_dir() / "fund_snapshots.jsonl"
