"""Config and secrets loading for the data router.

Mirrors `engine/incepta/config.py`'s `_load_dotenv()` pattern exactly: real
vendor keys (Alpha Vantage, OpenBB, Tiingo, ...) live in a gitignored
`data-router/.env` file, never in code, never in shell history, and are read
through `os.environ` so a model never sees them (a model never even imports
this module — only adapters do).

This sandbox has no network access and no real vendor keys are configured
anywhere. `.env` will not exist here, so every `*_API_KEY` lookup below comes
back empty and every real-vendor adapter stub raises
`router.adapters.base.VendorNotConfiguredError` — by design, not by accident.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load data-router/.env into the environment (without overwriting
    anything already set). Keeps vendor keys out of code and shell history.
    No third-party dependency — same approach as engine/incepta/config.py."""
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


def env(name: str) -> str:
    """Read an env var, stripped, defaulting to "". Centralized so every
    adapter reads secrets the same way."""
    return os.environ.get(name, "").strip()
