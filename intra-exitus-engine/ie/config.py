"""Central configuration for the Intra / Exitus engine.

One place for every external constant and path. Mirrors the discipline of the
Incepta engine's config but shares nothing with it — this engine is sealed.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Keeps the Tiingo key out of code and shell history.
    No third-party dependency."""
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


# --- Covered universe --------------------------------------------------------
# The names this entry/exit planner covers. Starts aligned with the equity
# engine's five for convenience. One list — extend it, re-run, re-export.
UNIVERSE: list[str] = ["AAPL", "MSFT", "NVDA", "KO", "F"]

# Bars before this date are not requested (keeps the free-tier footprint sane and
# gives every feature window room to warm up).
HISTORY_START = "2010-01-01"

# Trading days per year — the annualisation constant used across features.
TRADING_DAYS = 252


# --- Local storage -----------------------------------------------------------
def data_dir() -> Path:
    d = Path(os.environ.get("IE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def exports_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_root() -> Path:
    # intra-exitus-engine/ie/config.py -> parents[2] == repo root (hf/)
    return Path(__file__).resolve().parents[2]
