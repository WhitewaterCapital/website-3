"""Website handoff export — the one JSON the site reads.

Writes a contract-compliant JSON to:

  * <repo>/public/data/earnings/latest.json   (web-servable)
  * <engine>/exports/latest.json               (engine-side copy)

Run:  python -m ee.export

Gated exactly like every other engine here: build_export() looks for
FMP_API_KEY in os.environ.
  * KEY SET   -> FmpCalendarAdapter.get_earnings() for config.UNIVERSE over
    the lookahead window, labeled "data_provenance": "live". NOT YET
    EXERCISED END TO END — the adapter itself is an honest stub (see
    adapters/fmp_calendar.py); this path is wired and ready to work the
    moment a real HTTP call replaces the NotImplementedError there.
  * KEY UNSET -> ee.synthetic's deterministic fake panel, labeled
    "data_provenance": "synthetic-demo" — the never-touched fallback so the
    website seam has something to read with no key configured, same as
    every other engine in this repo.
The two provenances are never mixed within one export.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .config import (
    env,
    EARNINGS_CALENDAR_API_KEY_VAR,
    UNIVERSE,
    LOOKAHEAD_DAYS,
    SCHEMA_VERSION,
    ENGINE_VERSION,
    DISCLAIMER,
    repo_root,
    exports_dir,
)
from .synthetic import synthetic_events


def build_export(today: date | None = None) -> dict:
    today = today if today is not None else date.today()
    api_key = env(EARNINGS_CALENDAR_API_KEY_VAR)

    if api_key:
        from .adapters.fmp_calendar import FmpCalendarAdapter

        adapter = FmpCalendarAdapter()
        from datetime import timedelta

        events = adapter.get_earnings(UNIVERSE, today, today + timedelta(days=LOOKAHEAD_DAYS))
        provenance = "live"
    else:
        events = synthetic_events(today, UNIVERSE)
        provenance = "synthetic-demo"

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "universe": list(UNIVERSE),
        "lookahead_days": LOOKAHEAD_DAYS,
        "disclaimer": DISCLAIMER,
        "data_provenance": provenance,
        "events": events,
    }


def default_export_paths() -> list[Path]:
    return [
        repo_root() / "public" / "data" / "earnings" / "latest.json",
        exports_dir() / "latest.json",
    ]


def write_export(payload: dict, paths: list[Path] | None = None) -> list[Path]:
    """Write `payload` to `paths` (default: the real website + engine-copy
    locations). Tests pass their own `paths` so running the suite never
    overwrites the real handoff file — same convention as every export.py
    in this repo."""
    paths = paths if paths is not None else default_export_paths()
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    print(f"Exported {len(payload['events'])} events (as of {payload['as_of']}, {payload['data_provenance']}).")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
