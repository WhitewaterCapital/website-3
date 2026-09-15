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
`append_history`). A fund with no prior snapshot AND no usable proxy inputs
(see below) gets `flow_dollars = NaN`, which `compute_pressure` already
handles correctly on its own (that product is recorded in
`skipped_products`, never coerced to a fake zero flow) — no special-casing
needed here.

## What changed this pass (2026-09-14): NAV and typical_volume are now real,
## live inputs on the LIVE path — not unconditionally NaN/empty anymore

Two of this engine's own README-documented "still open" gaps are now wired
for real, each independently gated so a vendor being unreachable/
unconfigured degrades that ONE input honestly rather than blocking the
whole export:

  * **NAV per share** (`adapters/ishares_nav.py`, real, same
    `CASCADE_LIVE_HOLDINGS` gate as the holdings CSV — see that module's
    docstring for the confirmed research trail and its specific
    lower-confidence-than-the-CSV parsing caveat). When available, it feeds
    `estimate_flow_from_shares_outstanding`'s `nav_per_share` argument for
    a fund with a usable prior-day snapshot (this closes the exact gap
    config.py's DISCLAIMER used to describe: "even once a real second
    day's shares-outstanding reading exists, ... needs a NAV to price the
    delta ... currently passes nav_per_share=NaN"). For a fund with NO
    usable prior-day snapshot (every fund's very first live run), a real
    NAV is instead handed to `estimate_flow_proxy` ALONGSIDE the fund's own
    most-recent price/volume from Alpaca (below) — a genuine, if
    proxy-labelled (`is_proxy=True`), flow estimate on day one, rather than
    an automatic NaN until day two.
  * **typical_volume per constituent** (`adapters/alpaca_volume.py`, real,
    gated on `ALPACA_API_KEY_ID`/`ALPACA_API_SECRET_KEY` — the SAME two env
    var names `chaos-engine`'s own Alpaca adapter uses, intentionally, so
    one key pair lights up both engines; see that module's docstring for
    the full research trail). When configured and reachable, this replaces
    the always-empty `{}` this engine used to pass unconditionally on the
    live path. `compute_pressure`'s own documented contract already
    handles a ticker missing from `typical_volume` (excluded leg, reason
    recorded in `warnings`) — that contract is relied on here, not
    reimplemented, for any ticker Alpaca doesn't return a bar for.

NEITHER of these has been exercised successfully end to end in any sandbox
this engine has been built in — both `ishares.com` and
`data.alpaca.markets` hit the identical proxy-level policy denial
documented throughout this engine and `PLATFORM_REBUILD_PLAN.md`'s
Roadblocks. Each new adapter's own module docstring names this precisely.
The two provenances for holdings/pressure (live/synthetic-demo) are still
never mixed within one export; `typical_volume_provenance` is a SEPARATE,
independently-reported field for exactly this reason — a "live" pressure
export can legitimately carry `typical_volume_provenance: "not-configured"`
if only the iShares side is working, and that combination is not an
inconsistency, it's the honest state of two independently-gated inputs.
"""

from __future__ import annotations

import json
import math
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
    estimate_flow_proxy,
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


def _build_from_live(today: date) -> tuple[pd.DataFrame, list[FlowEstimate], list[dict], list[str], list[str]]:
    from .adapters.ishares_holdings import (
        IsharesHoldingsAdapter,
        LiveFetchFailedError as HoldingsLiveFetchFailedError,
    )
    from .adapters.ishares_nav import (
        IsharesNavAdapter,
        LiveFetchFailedError as NavLiveFetchFailedError,
    )
    from .adapters.alpaca_volume import (
        AlpacaDailyVolumeAdapter,
        LiveFetchFailedError as AlpacaLiveFetchFailedError,
    )

    holdings_adapter = IsharesHoldingsAdapter()
    nav_adapter = IsharesNavAdapter()
    alpaca_adapter = AlpacaDailyVolumeAdapter()
    existing_snapshots = _read_fund_snapshots(fund_snapshots_path())

    holdings_rows: list[dict] = []
    flows: list[FlowEstimate] = []
    new_snapshots: list[dict] = []
    skipped_funds: list[str] = []
    extra_warnings: list[str] = []

    for fund in FUNDS:
        try:
            snap = holdings_adapter.get_holdings(fund, as_of=today)
        except HoldingsLiveFetchFailedError as exc:
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

        # Real NAV per share — see adapters/ishares_nav.py's module
        # docstring for the confirmed research trail. Genuinely optional: a
        # failed or gated-off NAV fetch just degrades this fund's flow
        # exactly the way it always degraded before this pass (NaN), never
        # a fabricated NAV.
        nav_per_share = float("nan")
        try:
            nav_snap = nav_adapter.get_nav(fund, as_of=today)
            nav_per_share = nav_snap.nav_per_share
        except NavLiveFetchFailedError as exc:
            extra_warnings.append(
                f"{fund.ticker}: NAV fetch failed ({exc}); flow stays NaN unless a "
                f"proxy estimate below can be computed without it — it cannot, NAV is "
                f"required for both the direct and proxy methods."
            )

        prior = _prior_snapshot(existing_snapshots, fund.ticker, as_at)
        if prior is None or prior.get("shares_outstanding") is None or snap.shares_outstanding is None:
            # No usable prior day for the DIRECT (shares-outstanding-delta)
            # method — every fund's very first live run hits this. Try the
            # PROXY method (pressure.py::estimate_flow_proxy) instead of
            # automatically leaving flow at NaN until day two: it needs a
            # real NAV (above) plus the FUND's OWN most-recent price and
            # share volume, sourced from Alpaca (adapters/alpaca_volume.py)
            # — genuinely completes this README-documented gap for a
            # first-ever run, not just day two onward.
            flow: FlowEstimate | None = None
            if not math.isnan(nav_per_share) and alpaca_adapter.is_configured():
                try:
                    fund_bars = alpaca_adapter.latest_price_and_volume([fund.ticker])
                except AlpacaLiveFetchFailedError as exc:
                    extra_warnings.append(
                        f"{fund.ticker}: proxy flow not computed — Alpaca fetch for the "
                        f"fund's own price/volume failed: {exc}"
                    )
                else:
                    if fund.ticker in fund_bars:
                        price, volume_shares = fund_bars[fund.ticker]
                        flow = estimate_flow_proxy(
                            fund.ticker,
                            as_at,
                            volume_shares=volume_shares,
                            price=price,
                            nav_per_share=nav_per_share,
                        )
                    else:
                        extra_warnings.append(
                            f"{fund.ticker}: proxy flow not computed — Alpaca returned no "
                            f"daily bar for the fund's own ticker"
                        )
            if flow is None:
                flow = FlowEstimate(
                    product=fund.ticker,
                    as_at_date=as_at,
                    flow_dollars=float("nan"),
                    method="shares_outstanding",
                    is_proxy=False,
                )
            flows.append(flow)
        else:
            flows.append(
                estimate_flow_from_shares_outstanding(
                    fund.ticker,
                    as_at,
                    prior["shares_outstanding"],
                    snap.shares_outstanding,
                    nav_per_share=nav_per_share,
                )
            )

    if not holdings_rows:
        raise LiveExportFailedError(
            "CASCADE_LIVE_HOLDINGS is set but every fund's fetch failed: "
            + "; ".join(skipped_funds)
        )

    holdings_df = pd.DataFrame(holdings_rows, columns=list(HOLDINGS_COLUMNS))
    append_fund_snapshots(new_snapshots)
    return holdings_df, flows, new_snapshots, skipped_funds, extra_warnings


def _typical_volume_for_live(holdings_df: pd.DataFrame) -> tuple[dict[str, float], str, list[str]]:
    """Real `typical_volume` via Alpaca daily bars (adapters/alpaca_volume.py)
    for the LIVE holdings path only — the synthetic-demo path already has
    its own fabricated-on-a-fixed-seed typical_volume from synthetic.py,
    clearly labeled by `data_provenance == "synthetic-demo"` at the top
    level, so this function is never called for that path.

    Returns `(typical_volume, provenance_label, warnings)`. Alpaca being
    unconfigured or failing does NOT raise or block the export — the
    holdings/flow side of this export can be genuinely live even when
    Alpaca isn't reachable or configured, and `compute_pressure`'s own
    documented contract already turns a missing `typical_volume` entry
    into an honestly-excluded leg, not a crash. Never a fabricated number.
    """
    from .adapters.alpaca_volume import (
        AlpacaDailyVolumeAdapter,
        LiveFetchFailedError as AlpacaLiveFetchFailedError,
    )

    warnings: list[str] = []
    adapter = AlpacaDailyVolumeAdapter()
    if not adapter.is_configured():
        warnings.append(
            "typical_volume not sourced: ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY not "
            "configured — see cde/adapters/alpaca_volume.py. compute_pressure() will "
            "exclude every constituent-leg for lack of typical_volume, the same honest "
            "abstention this engine used for this gap before this pass."
        )
        return {}, "not-configured", warnings

    tickers = sorted(set(holdings_df["constituent"])) if not holdings_df.empty else []
    if not tickers:
        return {}, "not-configured", warnings

    try:
        tv = adapter.compute_typical_dollar_volume(tickers)
    except AlpacaLiveFetchFailedError as exc:
        warnings.append(f"typical_volume fetch from Alpaca failed: {exc}")
        return {}, "alpaca-fetch-failed", warnings

    missing = sorted(set(tickers) - set(tv))
    if missing:
        warnings.append(
            f"typical_volume: Alpaca returned no usable daily bars for {missing!r}; "
            f"those constituent-legs will be excluded by compute_pressure()."
        )
    provenance = "live-alpaca" if tv else "alpaca-empty"
    return tv, provenance, warnings


def build_export(today: date | None = None) -> dict:
    today = today if today is not None else date.today()
    live_enabled = env_flag(CASCADE_LIVE_HOLDINGS_VAR)

    skipped_funds: list[str] = []
    extra_warnings: list[str] = []
    if live_enabled:
        holdings_df, flows, snapshots, skipped_funds, extra_warnings = _build_from_live(today)
        provenance = "live"
        funds_used = sorted({f.ticker for f in FUNDS} - {s.split(":")[0] for s in skipped_funds})
        typical_volume, tv_provenance, tv_warnings = _typical_volume_for_live(holdings_df)
        extra_warnings.extend(tv_warnings)
    else:
        holdings_df, flows, snapshots, typical_volume = synthetic_snapshots(today)
        provenance = "synthetic-demo"
        funds_used = [f.ticker for f in FUNDS]
        tv_provenance = "synthetic-demo"

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
        "typical_volume_provenance": tv_provenance,
        "pressure": pressure_records,
        "skipped_products": list(result.skipped_products),
        "warnings": list(result.warnings) + extra_warnings,
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
        f"as of {payload['as_of']}, {payload['data_provenance']} "
        f"(typical_volume: {payload['typical_volume_provenance']})."
    )
    if payload["skipped_funds"]:
        print(f"  skipped funds: {payload['skipped_funds']}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
