"""Central configuration. All external-facing constants (URLs, the SEC rate
limit, the required User-Agent) live here so there is one place to audit them.

Verified against primary sources on 2026-08-04:
- SEC EDGAR REST APIs live under https://data.sec.gov and require **no API key**,
  but every request MUST carry a descriptive `User-Agent` header that names the
  requester and a contact email, or the SEC returns HTTP 403.
  https://www.sec.gov/os/accessing-edgar-data
- The SEC fair-access limit is **10 requests/second per IP**. We stay well under.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load engine/.env into the environment (without overwriting anything already
    set). Keeps secrets like TIINGO_API_KEY in a gitignored file, never in code or
    shell history. No third-party dependency."""
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

# --- SEC EDGAR endpoints -----------------------------------------------------
SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"
# ticker -> CIK mapping (small JSON, cached locally after first fetch)
SEC_COMPANY_TICKERS_URL = f"{SEC_WWW_BASE}/files/company_tickers.json"
# XBRL "company facts" — every reported fact for a filer, with filing dates.
SEC_COMPANY_FACTS_URL = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{{cik10}}.json"

# --- Fair-access compliance --------------------------------------------------
# SEC caps at 10 req/s; we self-limit to a conservative ~8 req/s (0.125s gap).
SEC_MIN_REQUEST_INTERVAL_S = 0.125
SEC_REQUEST_TIMEOUT_S = 30
SEC_MAX_RETRIES = 3


def sec_user_agent() -> str:
    """The SEC-mandated User-Agent. Read from env so we never commit a personal
    email. Format: "Org Name contact@domain". Raises if unset — failing loudly
    here is better than an opaque 403 from the SEC later.
    """
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT is not set. The SEC requires a descriptive "
            "User-Agent with a contact email or it returns HTTP 403. Set e.g.\n"
            '  export SEC_USER_AGENT="Four & Co. Research you@example.com"'
        )
    return ua


# --- Local storage -----------------------------------------------------------
def data_dir() -> Path:
    d = Path(os.environ.get("INCEPTA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def duckdb_path() -> Path:
    return data_dir() / "incepta.duckdb"
