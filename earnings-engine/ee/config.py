"""Central configuration for WW-EARNINGS.

Mirrors the discipline of factor-engine/fac/config.py and
weekly-engine/wf/config.py: one place for every tunable constant, a
gitignored per-engine .env loaded without a third-party dependency, and a
fixed live-vs-synthetic gate on a single named env var (see export.py).
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Duplicated (not imported) from the identical
    loader in factor-engine/intra-exitus-engine — this engine is sealed,
    same convention as every other engine in this repo."""
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


# --- Live-data gate ---------------------------------------------------------
# The one env var that decides live vs. synthetic-demo, checked in export.py
# exactly the way every other engine here gates on TIINGO_API_KEY. Financial
# Modeling Prep's free tier is the adapter this engine ships wired for (see
# adapters/fmp_calendar.py) because it's the source the platform's own
# research dossier names as having the best free coverage for earnings
# dates/actuals among the options checked — "FMP/Finnhub free (limited)".
EARNINGS_CALENDAR_API_KEY_VAR = "FMP_API_KEY"

# Same fixed 6-name universe every other cross-sectional screen in this repo
# uses (WW-Factor's DEFAULT_LIVE_UNIVERSE, Smart Money Momentum's
# SMART_MONEY_UNIVERSE, Intra/Exitus's covered set) — chosen for consistency
# across the platform's cross-sectional work, not invented fresh here.
UNIVERSE: list[str] = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"]

# How many calendar days ahead counts as "upcoming" for the website's
# earnings-window flag (idea-feed / earnings-move consumers). 21 days is
# roughly one month of trading days including a long weekend — wide enough
# that a weekly-cadence export still catches a print before it happens,
# narrow enough that "upcoming" doesn't drift into "sometime this quarter".
LOOKAHEAD_DAYS = 21

SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "0.1.0"

DISCLAIMER = (
    "Earnings dates/sessions only. NOT a surprise-direction or price-move "
    "prediction — see research/equity-model-research-dossier.md's own "
    "'Earnings-surprise direction' row (Medium confidence, needs analyst "
    "estimate data this engine does not fetch) for why that's out of scope "
    "here. Any positioning read attached to an event (insider activity, "
    "factor momentum) is a separate, already-real signal from elsewhere in "
    "this repo, not derived from the calendar data itself."
)


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # earnings-engine/ee/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
