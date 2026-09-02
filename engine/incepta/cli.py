"""Incepta engine CLI (slice 1).

    python -m incepta.cli ingest AAPL [MSFT ...]
    python -m incepta.cli asof AAPL 2021-01-15

`ingest` pulls a company's full XBRL history from SEC EDGAR and writes PIT facts
to the local DuckDB store. `asof` demonstrates the anti-look-ahead read: it shows
only what was public on that date.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

from .adapters.edgar import EdgarClient
from .store.duckdb_store import DuckDBStore


def _price_client():
    """Prefer Tiingo when a key is set; otherwise fall back to Stooq (which now
    fails honestly against its bot-detection wall). Import lazily so the engine
    works with no price provider at all."""
    if os.environ.get("TIINGO_API_KEY"):
        from .adapters.prices_tiingo import TiingoClient
        return TiingoClient()
    from .adapters.prices_stooq import StooqClient
    return StooqClient()


def _cmd_ingest(tickers: list[str]) -> int:
    edgar = EdgarClient()
    stooq = _price_client()
    store = DuckDBStore()
    try:
        for ticker in tickers:
            ticker = ticker.upper()
            print(f"→ {ticker}: SEC fundamentals + company info + prices …")

            cik = edgar.resolve_cik(ticker)
            if cik is None:
                print(f"  ! no CIK found for {ticker}; skipping")
                continue

            # 1) fundamentals (PIT)
            facts = edgar.fetch_facts(ticker)
            written = store.upsert_facts(facts)
            s = store.summary(ticker)

            # 2) company / sector
            info = edgar.company_info(cik)
            store.upsert_company(cik, ticker, info["name"], info["sic"], info["sic_description"])

            # 3) prices (needs a full-history start date; Tiingo returns only the
            #    latest bar otherwise)
            try:
                bars = stooq.fetch_prices(ticker, start=date(2005, 1, 1))
                n_px = store.upsert_prices(bars)
                px_range = f"{bars[0].date} → {bars[-1].date}" if bars else "none"
            except Exception as exc:  # noqa: BLE001 — surface, don't crash the batch
                n_px, px_range = 0, f"UNAVAILABLE ({exc})"

            print(
                f"  facts {written} ({s['first_reported_rows']} first-reported) | "
                f"periods {s['period_end_min']}→{s['period_end_max']}"
            )
            print(f"  sector: {info['sic_description'] or '?'} (SIC {info['sic'] or '?'})")
            print(f"  prices {n_px} bars | {px_range}")
    finally:
        store.close()
    return 0


def _cmd_asof(ticker: str, asof_str: str) -> int:
    try:
        asof = datetime.strptime(asof_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"Bad date {asof_str!r}; use YYYY-MM-DD", file=sys.stderr)
        return 2

    store = DuckDBStore()
    try:
        std = store.latest_standardized_asof(ticker, asof)
        if not std:
            print(
                f"No facts for {ticker.upper()} public on/before {asof}. "
                f"Have you run `ingest {ticker.upper()}`?"
            )
            return 1
        print(f"\n{ticker.upper()} — fundamentals knowable as of {asof} "
              f"(as-first-reported):\n")
        print(f"  {'field':<22}{'value':>20}  {'period end':<12}{'form':<7}filed")
        print("  " + "-" * 72)
        for field, v in std.items():
            print(
                f"  {field:<22}{v['value']:>20,.0f}  "
                f"{str(v['period_end']):<12}{v['form'] or '':<7}{v['filed']}"
            )
        print(
            "\n  ↑ Every row was already filed with the SEC on/before "
            f"{asof}. Nothing here leaks the future."
        )
    finally:
        store.close()
    return 0


def _cmd_quality(tickers: list[str], asof_str: str) -> int:
    from .pipeline import quality_ranking
    asof = (datetime.strptime(asof_str, "%Y-%m-%d").date() if asof_str
            else date.today())
    store = DuckDBStore()
    try:
        df = quality_ranking(store, [t.upper() for t in tickers], asof)
        if df.empty:
            print("No data. Run `ingest` for these tickers first.")
            return 1
        cols = ["sector", "roa", "gross_margin", "net_margin", "leverage",
                "piotroski_f", "score", "rank"]
        show = df[cols].copy()
        for c in ["roa", "gross_margin", "net_margin", "leverage"]:
            show[c] = (show[c] * 100).round(1)
        show["score"] = show["score"].round(2)
        show["rank"] = show["rank"].round(0)
        show["sector"] = show["sector"].str.slice(0, 22)
        print(f"\nCross-sectional QUALITY ranking (fundamentals only) as of {asof}:\n")
        print(show.to_string())
        print("\n  roa/margins/leverage in %, piotroski_f out of 9, rank = percentile.")
        print("  NOTE: quality-only (no valuation/momentum — those need a price key).")
    finally:
        store.close()
    return 0


def _cmd_analyze(tickers: list[str], asof_str: str) -> int:
    from .pipeline import risk_snapshot
    asof = datetime.strptime(asof_str, "%Y-%m-%d").date() if asof_str else None
    store = DuckDBStore()
    try:
        for t in tickers:
            r = risk_snapshot(store, t.upper(), asof)
            if r is None:
                print(f"\n{t.upper()}: not enough price history "
                      f"(ingest prices first; needs a TIINGO_API_KEY).")
                continue
            print(f"\n{r['ticker']} — risk read  (last close {r['last_close']:.2f}, "
                  f"{r['n_bars']} bars)")
            print(f"  momentum 12-1 : {r['mom_12_1']*100:6.1f}%    "
                  f"1m return : {r['ret_1m']*100:6.1f}%")
            print(f"  realized vol  : {r['realized_vol']*100:6.1f}%    "
                  f"downside vol: {r['downside_vol']*100:6.1f}%   (annualized)")
            print(f"  EWMA vol      : {r['ewma_vol']*100:6.1f}%    "
                  f"1y max DD : {r['max_dd_1y']*100:6.1f}%")
            print(f"  52w-high ratio: {r['high_52w_ratio']:6.2f}     "
                  f"est. spread: {r['spread_bps']:.1f} bps")
            print(f"  factor betas  : mkt {r['beta_mkt']:+.2f}  size {r['beta_smb']:+.2f}  "
                  f"value {r['beta_hml']:+.2f}  mom {r['beta_mom']:+.2f}")
            print(f"  factor R²     : {r['factor_r2']:.2f}   idiosyncratic vol: "
                  f"{r['idio_vol']*100:.1f}%   ({r['n_factor_obs']} days)")
    finally:
        store.close()
    return 0


def _cmd_export(tickers: list[str], asof_str: str, out: str) -> int:
    from pathlib import Path
    from .export import build_export, write_export

    asof = datetime.strptime(asof_str, "%Y-%m-%d").date() if asof_str else date.today()
    store = DuckDBStore()
    try:
        payload = build_export(store, [t.upper() for t in tickers], asof)
    finally:
        store.close()

    if out:
        paths = [out]
    else:
        engine_dir = Path(__file__).resolve().parents[1]
        repo_root = engine_dir.parent
        paths = [
            repo_root / "public" / "data" / "incepta" / "latest.json",  # web-servable
            engine_dir / "exports" / "latest.json",                     # engine copy
        ]
    written = write_export(payload, paths)

    conf = {}
    for s in payload["securities"]:
        conf[s["confidence"]] = conf.get(s["confidence"], 0) + 1
    print(f"Exported {len(payload['securities'])} securities (as of {asof}).")
    print(f"  confidence: {conf}")
    print("  written to:")
    for w in written:
        print(f"    {w}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="incepta", description="Incepta engine CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="ingest SEC EDGAR fundamentals + prices")
    p_ing.add_argument("tickers", nargs="+")

    p_as = sub.add_parser("asof", help="show fundamentals knowable as of a date")
    p_as.add_argument("ticker")
    p_as.add_argument("date")

    p_q = sub.add_parser("quality", help="cross-sectional quality ranking (fundamentals)")
    p_q.add_argument("tickers", nargs="+")
    p_q.add_argument("--asof", default="", help="YYYY-MM-DD (default: today)")

    p_an = sub.add_parser("analyze", help="price/risk read: vol, momentum, factor betas")
    p_an.add_argument("tickers", nargs="+")
    p_an.add_argument("--asof", default="", help="YYYY-MM-DD (default: latest)")

    p_ex = sub.add_parser("export", help="write the website handoff JSON")
    p_ex.add_argument("tickers", nargs="+")
    p_ex.add_argument("--asof", default="", help="YYYY-MM-DD (default: today)")
    p_ex.add_argument("--out", default="", help="output path (default: public/ + engine/exports/)")

    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        return _cmd_ingest(args.tickers)
    if args.cmd == "asof":
        return _cmd_asof(args.ticker, args.date)
    if args.cmd == "quality":
        return _cmd_quality(args.tickers, args.asof)
    if args.cmd == "analyze":
        return _cmd_analyze(args.tickers, args.asof)
    if args.cmd == "export":
        return _cmd_export(args.tickers, args.asof, args.out)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
