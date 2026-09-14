"""Website handoff export — the one JSON the site reads for WW-CASCADE.

Writes a contract-compliant JSON to:

  * <repo>/public/data/cascade/latest.json   (web-servable)
  * <engine>/exports/latest.json              (engine-side copy)

Run:  python -m cde.export

Gated exactly like every other engine here: build_export() looks for
CASCADE_LIVE_HOLDINGS (a flag, not a key — see config.py's module docstring
for why).

  * FLAG UNSET -> a deterministic synthetic-demo panel (`synthetic.py`),
    labeled "data_provenance": "synthetic-demo" — the never-touched
    fallback so the website seam has something to read with no live
    network configured, same as every other engine in this repo.
  * FLAG SET   -> IsharesHoldingsAdapter.get_holdings() for real, for every
    fund in config.FUNDS, labeled "data_provenance": "live" IF AT LEAST ONE
    fund's fetch succeeds (any fund that fails is recorded in
    `skipped_funds` with its real error, not silently dropped). If EVERY
    fund's fetch fails, this raises `LiveExportFailedError` rather than
    writing a "live" export with nothing real in it — see that class's
    docstring. NOT YET EXERCISED SUCCESSFULLY end to end in any sandbox
    this engine has been built in (see adapters/ishares_holdings.py's
    module docstring for the confirmed reason: this repo's own sandboxes
    are proxy-blocked from ishares.com itself, even though the endpoint is
    now confirmed real and reachable from a normal network).

Either way, holdings are handed to `quant_infra.cascade.pressure.
compute_pressure` for real — this is not a placeholder call. Flow is
estimated via shares-outstanding deltas against the PRIOR run's snapshot
(`state/fund_snapshots.jsonl`, appended every run — see
`append_fund_snapshots`, which mirrors graph-engine/ge/export.py's
`append_history`). A fund with no prior snapshot (every fund, on this
engine's first-ever run) gets `flow_dollars = NaN`, which `compute_pressure`
already handles correctly on its own (that product is recorded in
`skipped_products`, never coerced to a fake zero flow) — no special-casing
needed here. `typical_volume` is passed as an empty mapping: it is not
sourced anywhere in this pass (see config.py's DISCLAIMER for why) and
`compute_pressure` already handles a missing typical_volume the same
honest way. The two provenances (live/synthetic-demo) are never mixed
within one export.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .config import (
    CASCADE_LIVE_HOLDINGS_VAR,
    DISCLAIMER,
    ENGINE_VERSION,
    FUNDS,
    SCHEMA_VERSION,
    env_flag,
    exports_dir,
    fund_snapshots_path,
    repo_root,
)
from .synthetic import synthetic_snapshots

# quant-infra/cascade is a separate top-level package (not a Python
# distribution, no setup.py/pyproject.toml — same "add its directory to
# sys.path directly" situation its own tests are in). Importing it here,
# never editing it — quant-infra/cascade/*.py is untouched by this engine.
_CASCADE_MATH_DIR = repo_root() / "quant-infra" / "cascade"
if str(_CASCADE_MATH_DIR) not in sys.path:
    sys.path.insert(0, str(_CASCADE_MATH_DIR))

import pandas as pd  # noqa: E402

from pressure import (  # noqa: E402
    FlowEstimate,
    HOLDINGS_COLUMNS,
    compute_pressure,
    estimate_flow_from_shares_outstanding,
)


class LiveExportFailedError(RuntimeError):
    """Raised when CASCADE_LIVE_HOLDINGS is set but EVERY fund's real fetch
    failed — writing a "live" export with zero real funds in it would be a
    quieter, more dangerous version of exactly the fabrication this repo's
    culture refuses. Callers see the per-fund errors that caused it."""


def _read_fund_snapshots(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_fund_snapshots(snapshots: list[dict], path: Path | None = None, max_entries_per_fund: int = 180) -> Path:
    """Append this run's per-fund snapshots (ticker, as_at_date,
    shares_outstanding) to a small rotating JSONL log, one line per
    (fund, run) — mirrors graph-engine/ge/export.py's `append_history`
    exactly (same re-run-same-day-replaces-not-duplicates rule, same
    read/rewrite-whole-file simplicity, justified there and here by a small
    universe run at most a few times a day). This log is INTERNAL engine
    state (not written under public/data/) — the website only ever reads
    the already-computed pressure in latest.json, never this log directly.
    """
    path = path if path is not None else fund_snapshots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_fund_snapshots(path)
    by_key = {(s["ticker"], s["as_at_date"]): s for s in existing}
    for s in snapshots:
        by_key[(s["ticker"], s["as_at_date"])] = s  # replace same-day re-run, don't duplicate
    # Keep the most recent max_entries_per_fund snapshots per ticker.
    by_ticker: dict[str, list[dict]] = {}
    for s in by_key.values():
        by_ticker.setdefault(s["ticker"], []).append(s)
    kept: list[dict] = []
    for ticker, snaps in by_ticker.items():
        snaps.sort(key=lambda s: s["as_at_date"])
        kept.extend(snaps[-max_entries_per_fund:])
    kept.sort(key=lambda s: (s["ticker"], s["as_at_date"]))
    path.write_text("\n".join(json.dumps(s) for s in kept) + ("\n" if kept else ""))
    return path


def _prior_snapshot(existing: list[dict], ticker: str, before: str) -> dict | None:
    candidates = [s for s in existing if s["ticker"] == ticker and s["as_at_date"] < before]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["as_at_date"])


def _build_from_live(today: date) -> tuple[pd.DataFrame, list[FlowEstimate], list[dict], list[str]]:
    from .adapters.ishares_holdings import IsharesHoldingsAdapter, LiveFetchFailedError

    adapter = IsharesHoldingsAdapter()
    existing_snapshots = _read_fund_snapshots(fund_snapshots_path())

    holdings_rows: list[dict] = []
    flows: list[FlowEstimate] = []
    new_snapshots: list[dict] = []
    skipped_funds: list[str] = []

    for fund in FUNDS:
        try:
            snap = adapter.get_holdings(fund, as_of=today)
        except LiveFetchFailedError as exc:
            skipped_funds.append(f"{fund.ticker}: {exc}")
            continue

        as_at = snap.as_at_date.isoformat()
        for row in snap.holdings:
            holdings_rows.append(
                {
                    "product": fund.ticker,
                    "constituent": row["constituent"],
                    "weight": row["weight"],
                    "as_at_date": as_at,
                }
            )

        new_snapshots.append(
            {
                "ticker": fund.ticker,
                "as_at_date": as_at,
                "shares_outstanding": snap.shares_outstanding,
            }
        )

        prior = _prior_snapshot(existing_snapshots, fund.ticker, as_at)
        if prior is None or prior.get("shares_outstanding") is None or snap.shares_outstanding is None:
            # No usable prior day (or missing NAV data to price the delta) —
            # NaN flow, exactly the "unknown, not zero" contract
            # estimate_flow_from_shares_outstanding documents. NAV per share
            # isn't available from this CSV at all (see README's open items),
            # so even WITH a prior day this engine cannot price the delta —
            # flagged as flow_dollars=NaN via nav_per_share=NaN rather than
            # guessing a price.
            flows.append(
                FlowEstimate(
                    product=fund.ticker,
                    as_at_date=as_at,
                    flow_dollars=float("nan"),
                    method="shares_outstanding",
                    is_proxy=False,
                )
            )
        else:
            flows.append(
                estimate_flow_from_shares_outstanding(
                    fund.ticker,
                    as_at,
                    prior["shares_outstanding"],
                    snap.shares_outstanding,
                    nav_per_share=float("nan"),  # not sourced — see README open items
                )
            )

    if not holdings_rows:
        raise LiveExportFailedError(
            "CASCADE_LIVE_HOLDINGS is set but every fund's fetch failed: "
            + "; ".join(skipped_funds)
        )

    holdings_df = pd.DataFrame(holdings_rows, columns=list(HOLDINGS_COLUMNS))
    append_fund_snapshots(new_snapshots)
    return holdings_df, flows, new_snapshots, skipped_funds


def build_export(today: date | None = None) -> dict:
    today = today if today is not None else date.today()
    live_enabled = env_flag(CASCADE_LIVE_HOLDINGS_VAR)

    skipped_funds: list[str] = []
    if live_enabled:
        holdings_df, flows, snapshots, skipped_funds = _build_from_live(today)
        provenance = "live"
        funds_used = sorted({f.ticker for f in FUNDS} - {s.split(":")[0] for s in skipped_funds})
        # typical_volume is not sourced anywhere in this pass for the LIVE
        # path (see config.DISCLAIMER) — compute_pressure's own documented
        # contract already handles a missing/empty typical_volume honestly
        # (every affected leg excluded, NaN pressure, reason recorded in
        # `warnings`), so passing {} here is correct, not a shortcut.
        typical_volume: dict[str, float] = {}
    else:
        holdings_df, flows, snapshots, typical_volume = synthetic_snapshots(today)
        provenance = "synthetic-demo"
        funds_used = [f.ticker for f in FUNDS]

    result = compute_pressure(holdings_df, flows, typical_volume=typical_volume)

    pressure_records = json.loads(result.pressure.to_json(orient="records"))

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "funds": [f.ticker for f in FUNDS],
        "funds_used": funds_used,
        "skipped_funds": skipped_funds,
        "disclaimer": DISCLAIMER,
        "data_provenance": provenance,
        "pressure": pressure_records,
        "skipped_products": list(result.skipped_products),
        "warnings": list(result.warnings),
    }


def default_export_paths() -> list[Path]:
    return [
        repo_root() / "public" / "data" / "cascade" / "latest.json",
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
    n = len(payload["pressure"])
    n_usable = sum(1 for r in payload["pressure"] if r.get("pressure") is not None)
    print(
        f"Exported pressure for {n} constituents ({n_usable} with a non-NaN value) "
        f"as of {payload['as_of']}, {payload['data_provenance']}."
    )
    if payload["skipped_funds"]:
        print(f"  skipped funds: {payload['skipped_funds']}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
