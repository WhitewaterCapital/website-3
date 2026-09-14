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

TIER B (added 2026-09-14, see adapters/alpha_vantage_estimates.py's
docstring for the full provider survey): every event, live or synthetic,
additionally carries eps_estimate_stdev/estimate_source/sue/
sue_abstain_reason. These are SEPARATELY gated on
EARNINGS_ESTIMATES_API_KEY_VAR (Alpha Vantage) rather than FMP_API_KEY,
because FMP's free tier does not cover analyst estimates at all — a
calendar-only FMP key does not imply an estimates key is also usable, so
the two gates must not be conflated. `sue` is null on literally every
event this engine can currently produce, live or synthetic: every export
is pre-print by construction (report_date always in the future — see
config.LOOKAHEAD_DAYS), and SUE is undefined before the actual EPS behind
it exists. See ee/sue.py for why that function still exists and is fully
tested despite never firing a non-null result from this export today.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .config import (
    env,
    EARNINGS_CALENDAR_API_KEY_VAR,
    EARNINGS_ESTIMATES_API_KEY_VAR,
    UNIVERSE,
    LOOKAHEAD_DAYS,
    SCHEMA_VERSION,
    ENGINE_VERSION,
    DISCLAIMER,
    repo_root,
    exports_dir,
)
from .synthetic import synthetic_events
from .sue import compute_sue


def _enrich_with_estimates(event: dict) -> dict:
    """Attaches Tier-B fields to one LIVE event dict in place (and returns
    it, for convenient use in a comprehension). Honestly abstains — never
    fabricates a number — whenever the estimates adapter isn't configured
    or isn't implemented yet, which today is unconditionally the case (see
    adapters/alpha_vantage_estimates.py: it is a zero-network-call honest
    stub, same as adapters/fmp_calendar.py was before this engine had any
    live path at all)."""
    api_key = env(EARNINGS_ESTIMATES_API_KEY_VAR)
    if not api_key:
        event["eps_estimate_stdev"] = None
        event["estimate_source"] = None
        event["sue"] = None
        event["sue_abstain_reason"] = (
            f"{EARNINGS_ESTIMATES_API_KEY_VAR} not set — no analyst-estimates "
            f"adapter configured for this run"
        )
        return event

    from .adapters.alpha_vantage_estimates import (
        AlphaVantageEstimatesAdapter,
        VendorNotConfiguredError,
    )

    adapter = AlphaVantageEstimatesAdapter()
    try:
        inputs = adapter.get_estimate_inputs(event["ticker"])
    except (VendorNotConfiguredError, NotImplementedError) as exc:
        event["eps_estimate_stdev"] = None
        event["estimate_source"] = None
        event["sue"] = None
        event["sue_abstain_reason"] = f"estimates adapter unavailable: {exc}"
        return event

    # A real adapter response wins over whatever the calendar adapter put
    # in eps_estimate (which, per fmp_calendar.py, FMP's free tier cannot
    # actually populate anyway — see that adapter's docstring) since
    # Alpha Vantage's EARNINGS_CALENDAR is the one source this engine has
    # evidence is free for the forward consensus figure.
    if inputs.get("eps_estimate") is not None:
        event["eps_estimate"] = inputs["eps_estimate"]
    event["eps_estimate_stdev"] = inputs.get("eps_estimate_stdev")
    event["estimate_source"] = inputs.get("estimate_source")

    sue, reason = compute_sue(
        event.get("eps_actual"), event.get("eps_estimate"), event.get("eps_estimate_stdev")
    )
    event["sue"] = sue
    event["sue_abstain_reason"] = reason
    return event


def build_export(today: date | None = None) -> dict:
    today = today if today is not None else date.today()
    api_key = env(EARNINGS_CALENDAR_API_KEY_VAR)

    if api_key:
        from .adapters.fmp_calendar import FmpCalendarAdapter
        from datetime import timedelta

        adapter = FmpCalendarAdapter()
        events = adapter.get_earnings(UNIVERSE, today, today + timedelta(days=LOOKAHEAD_DAYS))
        events = [_enrich_with_estimates(e) for e in events]
        provenance = "live"
    else:
        # synthetic_events() already ships the Tier-B fields with their own
        # synthetic-appropriate honest-null shape (see synthetic.py) — not
        # re-enriched here, so a synthetic export never accidentally reads
        # as "we tried a real estimates lookup" when the whole calendar
        # under it is fake.
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
