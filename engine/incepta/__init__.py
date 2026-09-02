"""Incepta — the Python quantitative engine for the Four & Co. platform.

Deterministic math on real, point-in-time data. No LLM lives here.
"""

import warnings as _warnings

# Cosmetic only: macOS system Python links LibreSSL, which urllib3 v2 warns about.
# It does not affect requests/TLS correctness. Silence it so logs stay readable.
_warnings.filterwarnings("ignore", message=r".*OpenSSL.*", module="urllib3")

# Importing config runs its .env loader, so secrets (SEC_USER_AGENT,
# TIINGO_API_KEY) from engine/.env are available anywhere in the package.
from . import config as _config  # noqa: E402,F401

__version__ = "0.1.0"
