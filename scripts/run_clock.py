#!/usr/bin/env python3
"""ORCH-01 / IMP-07 — the unified clock driver: real wall-clock time, the
REAL scheduler/market-hours objects, and the REAL engine export entry
points, wired together into one command a GitHub Actions cron job can call.

    python scripts/run_clock.py {macro|equity|chaos} [--force]

Everything this script consults or invokes is real, already-tested code
that already existed before this file:

  * `quant-infra/orch/clocks/three_clocks.py`'s `MACRO_CLOCK` / `EQUITY_CLOCK`
    / `CHAOS_CLOCK` — the actual `ClockJob`s (cadence string, whether the job
    requires market hours), not a parallel/reinvented scheduling concept.
  * `quant-infra/orch/clocks/market_hours.py`'s `MarketHoursGate`, driven by
    the REAL NYSE trading calendar in
    `data-router/router/universe_publish/calendar_data.py` (`nyse_calendar`),
    via the same `adapt_venue_calendar` seam
    `quant-infra/orch/tests/test_market_hours_integration.py` already proves
    works against that concrete calendar. This script adds both sibling
    top-level packages (`quant-infra/orch` and `data-router`) to `sys.path`
    itself, mirroring exactly the path-handling trick that integration test
    already uses (see `_REPO_ROOT` / `_DATA_ROUTER_ROOT` there) — there is no
    shared install step across these sealed packages.
  * `quant-infra/orch/scheduler.py`'s `parse_cadence` — used to size the
    idempotent-replay window from the SAME cadence string the real
    `ClockJob` declares ("12h" / "1h" / "1-5min"), not a hardcoded duplicate.
  * Each clock's real engine export entry point, invoked as a real
    subprocess using the exact working-directory + module invocation each
    engine's own `export.py` docstring documents under "Run:":
      - macro  -> `engine/incepta/export_state.py`   (python -m incepta.export_state, cwd=engine/)
      - equity -> `weekly-engine/wf/export.py`        (python -m wf.export,        cwd=weekly-engine/)
                  `graph-engine/ge/export.py`         (python -m ge.export,        cwd=graph-engine/)
                  `quant-infra/alloc/export.py`       (python export.py,           cwd=quant-infra/alloc/)
      - chaos  -> `chaos-engine/chaos/export.py`      (python -m chaos.export,     cwd=chaos-engine/)
    (Equity gets all three per this repo's own model-registry table: weekly,
    graph, and alloc are all hourly-during-market-hours models.)

What this script is the one legitimate place to do, which nothing else in
this repo should: use `datetime.now(timezone.utc)` as "now". Every clock
unit test uses `orch.scheduler.ManualClock` instead — this file is where a
real wall clock is supposed to live.

Idempotent replay (the literal ORCH-01 requirement): a run log
(`ops/clock_runs/<clock>.jsonl`, one JSON object per line, append-only and
committed to git — see `ops/clock_runs/README.md`) is consulted before doing
any real work. If the clock's last GENUINELY SUCCESSFUL real run happened
more recently than its own cadence window (via `parse_cadence` on the real
`ClockJob.spec.cadence`), a second call in that same window is reported as
"already ran for this window" and does not re-invoke any engine — unless
`--force` is passed. A prior FAILED or SKIPPED run never blocks a retry;
only a real success starts the window, so a transient failure can always be
retried immediately without needing `--force`.

Exit code: 0 on a real success or a clean skip (idempotent-replay or
market-hours), non-zero on a genuine failure — so CI can alert on the
non-zero case and treat everything else as fine.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCH_ROOT = REPO_ROOT / "quant-infra" / "orch"
DATA_ROUTER_ROOT = REPO_ROOT / "data-router"
RUNS_DIR = REPO_ROOT / "ops" / "clock_runs"

# --- import the REAL scheduler / market-hours / clock objects ---------------
# Same cross-package sys.path trick as
# quant-infra/orch/tests/test_market_hours_integration.py: `orch` and
# `data-router` are separate sealed top-level packages with no shared install
# step, so each is inserted onto sys.path explicitly, once, right here.
for _p in (str(ORCH_ROOT), str(DATA_ROUTER_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clocks.market_hours import MarketHoursGate, adapt_venue_calendar  # noqa: E402
from clocks.three_clocks import CHAOS_CLOCK, EQUITY_CLOCK, MACRO_CLOCK, ClockJob  # noqa: E402
from router.universe_publish.calendar_data import nyse_calendar  # noqa: E402
from scheduler import parse_cadence  # noqa: E402

CLOCKS: dict[str, ClockJob] = {
    "macro": MACRO_CLOCK,
    "equity": EQUITY_CLOCK,
    "chaos": CHAOS_CLOCK,
}

# Each clock's real engine export entry points. `cmd` is run with `cwd` as
# the working directory, exactly matching that engine's own export.py
# docstring's documented "Run:" line — no engine's import style is bent to
# suit this driver.
ENGINE_JOBS: dict[str, list[dict]] = {
    "macro": [
        {"name": "incepta_state", "cwd": REPO_ROOT / "engine", "cmd": [sys.executable, "-m", "incepta.export_state"]},
    ],
    "equity": [
        {"name": "weekly", "cwd": REPO_ROOT / "weekly-engine", "cmd": [sys.executable, "-m", "wf.export"]},
        {"name": "graph", "cwd": REPO_ROOT / "graph-engine", "cmd": [sys.executable, "-m", "ge.export"]},
        {"name": "alloc", "cwd": REPO_ROOT / "quant-infra" / "alloc", "cmd": [sys.executable, "export.py"]},
    ],
    "chaos": [
        {"name": "chaos", "cwd": REPO_ROOT / "chaos-engine", "cmd": [sys.executable, "-m", "chaos.export"]},
    ],
}


@dataclass
class EngineResult:
    name: str
    success: bool
    detail: str
    returncode: int | None
    output_tail: str


def run_engine_job(job: dict) -> EngineResult:
    """Invoke one engine's export entry point as a real subprocess."""
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            job["cmd"],
            cwd=str(job["cwd"]),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except Exception as exc:  # e.g. interpreter not found, timeout
        return EngineResult(job["name"], False, f"subprocess failed to start/run: {exc!r}", None, "")

    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(combined.strip().splitlines()[-20:])
    success = proc.returncode == 0
    detail = "ok" if success else f"exit code {proc.returncode}"
    return EngineResult(job["name"], success, detail, proc.returncode, tail)


def build_gate() -> MarketHoursGate:
    """Real `MarketHoursGate` wired to the REAL, stored NYSE calendar (not a
    fake/stub) — genuine integration, same as
    `test_market_hours_integration.py`."""
    venue_calendar = nyse_calendar()
    return MarketHoursGate(venue="NYSE", calendar=adapt_venue_calendar(venue_calendar))


# --- run log (ops/clock_runs/<clock>.jsonl) ---------------------------------

def _log_path(clock_name: str) -> Path:
    return RUNS_DIR / f"{clock_name}.jsonl"


def load_run_log(clock_name: str) -> list[dict]:
    path = _log_path(clock_name)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a corrupt line never blocks reading the rest of the log
    return records


def append_run_log(clock_name: str, record: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = _log_path(clock_name)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def last_successful_real_run_at(records: list[dict]) -> datetime | None:
    """Most recent record where the clock genuinely executed AND every
    engine invoked succeeded — the only kind of prior run that starts an
    idempotent-replay window. A skipped run (market-closed or
    already-ran-this-window) or a run where an engine failed never blocks a
    subsequent attempt: only a real, clean success does."""
    for r in reversed(records):
        if r.get("ran_for_real") and r.get("overall_status") == "success":
            try:
                return datetime.fromisoformat(r["timestamp"])
            except (KeyError, ValueError):
                continue
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clock", choices=sorted(CLOCKS.keys()), help="which clock to run")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "bypass BOTH the market-hours gate and the idempotent-replay window. "
            "For manual/testing use only — never pass this in routine scheduled automation."
        ),
    )
    args = parser.parse_args(argv)

    clock_name = args.clock
    clock_job = CLOCKS[clock_name]
    now = datetime.now(timezone.utc)  # the one real wall clock in this whole codebase

    records = load_run_log(clock_name)
    cadence_window: timedelta = parse_cadence(clock_job.spec.cadence)
    last_success = last_successful_real_run_at(records)

    # --- idempotent replay -------------------------------------------------
    if not args.force and last_success is not None:
        age = now - last_success
        if age < cadence_window:
            record = {
                "timestamp": now.isoformat(),
                "clock": clock_name,
                "cadence": clock_job.spec.cadence,
                "ran_for_real": False,
                "forced": False,
                "overall_status": "skipped_already_ran_window",
                "detail": (
                    f"already ran successfully for this {clock_job.spec.cadence} window "
                    f"(last success {last_success.isoformat()}, {age} ago, window {cadence_window}); "
                    "ORCH-01 idempotent replay — pass --force to override."
                ),
                "engines": [],
            }
            append_run_log(clock_name, record)
            print(
                f"[{clock_name}] SKIP: already ran for this window "
                f"(last success {last_success.isoformat()}, {age} ago, cadence={clock_job.spec.cadence}). "
                "Pass --force to re-run anyway."
            )
            return 0

    # --- market-hours gate ---------------------------------------------------
    gate = build_gate()
    allowed, reason = gate.should_run(now, clock_job.requires_market_hours)

    if args.force and not allowed:
        print(
            f"[{clock_name}] FORCE OVERRIDE: the market-hours gate would have refused this run "
            f"({reason}), but --force was passed so it is running anyway. This bypasses IMP-07's "
            "market-hours protection and must only be used for manual/testing runs, never routine "
            "scheduled automation."
        )
    elif not allowed:
        record = {
            "timestamp": now.isoformat(),
            "clock": clock_name,
            "cadence": clock_job.spec.cadence,
            "ran_for_real": False,
            "forced": False,
            "overall_status": "skipped_market_closed",
            "market_hours_gate": {"allowed": allowed, "reason": reason},
            "detail": f"market-hours gate refused: {reason}",
            "engines": [],
        }
        append_run_log(clock_name, record)
        print(f"[{clock_name}] SKIP: market-hours gate refused this run ({reason}).")
        return 0

    if args.force and last_success is not None and (now - last_success) < cadence_window:
        print(
            f"[{clock_name}] FORCE OVERRIDE: also bypassing the idempotent-replay window "
            f"(last success {last_success.isoformat()}); running again anyway because --force was passed."
        )

    # --- run every engine assigned to this clock, for real ------------------
    jobs = ENGINE_JOBS[clock_name]
    results = [run_engine_job(job) for job in jobs]
    all_ok = all(r.success for r in results)

    record = {
        "timestamp": now.isoformat(),
        "clock": clock_name,
        "cadence": clock_job.spec.cadence,
        "ran_for_real": True,
        "forced": args.force,
        "market_hours_gate": {"allowed": allowed, "reason": reason},
        "overall_status": "success" if all_ok else "failed",
        "engines": [
            {"name": r.name, "success": r.success, "detail": r.detail, "returncode": r.returncode}
            for r in results
        ],
    }
    append_run_log(clock_name, record)

    print(f"[{clock_name}] running {len(results)} engine(s) for real (market-hours gate: {reason}).")
    for r in results:
        status = "OK" if r.success else "FAILED"
        print(f"  - {r.name}: {status} ({r.detail})")
        if not r.success and r.output_tail:
            print(textwrap.indent(r.output_tail, "      "))

    if all_ok:
        print(f"[{clock_name}] all {len(results)} engine(s) ran successfully.")
        return 0
    print(f"[{clock_name}] one or more engines FAILED — see output above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
