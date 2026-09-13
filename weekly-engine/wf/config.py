"""Central configuration for WW-WEEKLY.

Mirrors the discipline of ie/config.py and engine/incepta's config — one place
for constants and paths — but shares nothing with either. This engine now has
a real, sealed Tiingo adapter (`wf/adapters/prices_tiingo.py`) gated on
`TIINGO_API_KEY`: `export.py` runs live whenever that key is set in
`os.environ`, and falls back to the original synthetic/demo mode otherwise.
See README.md ("What a real run needs") for the full picture.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Keeps the Tiingo key out of code and shell history.
    Identical in behaviour to intra-exitus-engine/ie/config.py's loader
    (duplicated, not imported — this engine is sealed). No third-party
    dependency."""
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

# --- Universe & sectors -------------------------------------------------
# A small illustrative universe with sector tags, used only for the synthetic
# demo export (no real point-in-time price history is available in this
# sandbox). A real deployment would source both from a maintained universe
# file, point-in-time (constituents change; sector tags drift).
UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",   # tech / consumer disc.
    "JPM", "BAC", "GS",                          # financials
    "XOM", "CVX",                                 # energy
    "KO", "PEP",                                   # staples
    "JNJ", "PFE",                                   # healthcare
    "F", "GM",                                       # autos
]

SECTOR_MAP: dict[str, str] = {
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "GOOGL": "tech", "AMZN": "tech",
    "JPM": "financials", "BAC": "financials", "GS": "financials",
    "XOM": "energy", "CVX": "energy",
    "KO": "staples", "PEP": "staples",
    "JNJ": "healthcare", "PFE": "healthcare",
    "F": "autos", "GM": "autos",
}

# Weeks per year, for annualisation.
TRADING_WEEKS_PER_YEAR = 52

# One-week embargo after each walk-forward test block (spec: "purged
# walk-forward with a one-week embargo").
EMBARGO_WEEKS = 1

# The label's forward horizon in weeks. Purge distance in the CV splitter
# MUST equal this (see validation/splits.py's docstring) or a training
# label's forward window can silently overlap the test block.
LABEL_HORIZON_WEEKS = 1


# --- Live data (real Tiingo prices) --------------------------------------
# Used ONLY when TIINGO_API_KEY is set (see wf/adapters/prices_tiingo.py and
# wf/export.py) — UNIVERSE/SECTOR_MAP above are unchanged either way; this
# only controls how much daily history a live run asks Tiingo for before
# resampling to weekly. 2010-01-01 matches intra-exitus-engine's own
# HISTORY_START and gives, after weekly resampling, well over the
# DEMO_N_WEEKS=320 the synthetic calibration in export.py uses — enough
# post-warmup (52-week momentum/dist-from-high lookback) weeks left for
# several purged walk-forward folds, same as README.md "What a real run
# needs" point 3 asks for.
LIVE_HISTORY_START = "2010-01-01"


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # weekly-engine/wf/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
