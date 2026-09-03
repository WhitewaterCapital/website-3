"""Central configuration for WW-WEEKLY.

Mirrors the discipline of ie/config.py and engine/incepta's config — one place
for constants and paths — but shares nothing with either. This engine is
sealed: it has no live data adapter in this sandbox (no Tiingo/EDGAR client),
so `export.py` always runs in synthetic/demo mode here. See README.md
("What a real run needs") for what plugging in real point-in-time weekly
price history would require.
"""

from __future__ import annotations

from pathlib import Path

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


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # weekly-engine/wf/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
