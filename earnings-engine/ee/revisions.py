"""Revision momentum — direction/magnitude of REAL changes to this engine's
own recorded consensus-EPS-estimate snapshots over time.

WHY THIS MODULE EXISTS (and why it did not exist before 2026-09-14): the
platform's original research dossier and this engine's own Tier-B pass
(see README.md's "Tier B" section, adapters/alpha_vantage_estimates.py's
docstring) both named "revision momentum" — an estimate getting raised or
lowered repeatedly ahead of a print is itself a real, well-documented PEAD-
adjacent signal, distinct from SUE (which needs the print to have already
happened) — as worth having. It was explicitly NOT built in the Tier-B
pass, for a data-access reason stated plainly in this engine's own
README.md at the time: "Alpha Vantage's free endpoints only expose the
CURRENT consensus estimate, not point-in-time snapshots of how it moved —
computing a revision needs this engine to start storing its own weekly
snapshots over time, which is real infrastructure work, not a data-access
problem." This module is that infrastructure work.

HOW IT WORKS: every time export.py runs — in EITHER live or synthetic-demo
mode, since both modes attach an `eps_estimate` to every event and a
revision read only cares about "what estimate did this engine record for
this ticker on which date," not where that estimate came from —
`record_and_compute_revisions()` is called once per export with that run's
full event list and its `as_of` date. For each event it:

  1. Reads the ticker's PRIOR recorded snapshots (if any) from the
     append-only log at config.estimate_snapshots_path(), BEFORE this
     run's own value is written to it — so a revision is always computed
     against a REAL, previously-observed value, never against the value
     this same run is about to record.
  2. Computes an honest (direction, pct, abstain_reason) triple via the
     pure `compute_revision()` function below — abstaining, with a stated
     reason, whenever there is not yet a usable prior snapshot to compare
     against. On a fresh log (this engine's first-ever run, or a ticker's
     first appearance in it) this is the ONLY possible outcome — abstention
     is not a bug here, it is the honest, expected, and (for a while) most
     common state of this field, exactly the way `ee/sue.py`'s `sue` field
     is honestly null on every event this engine can currently produce.
  3. Appends this run's own (ticker, eps_estimate, as_of_date) snapshot to
     the log, so a FUTURE run has real history to compare against.

SNAPSHOT-LOG PATTERN: deliberately NOT invented fresh here. This mirrors
two existing, already-real precedents in this repo, chosen over a third
option (a database) for the same reason both of them were: a small,
durable, append-only history log, capped/rotated so it never grows
unbounded, is enough for a single-digit-name universe checked at most a
few times a day, and needs no new infrastructure.

  * cascade-data-engine/cde/export.py's `append_fund_snapshots()` /
    `_read_fund_snapshots()` / `_prior_snapshot()` — the closer precedent:
    same "most recent snapshot strictly BEFORE this run's date" lookup
    this module's `_prior_snapshot()` copies almost verbatim, same
    same-day-rerun-REPLACES-not-duplicates rule, same
    read-whole-file/rewrite-whole-file simplicity (justified there and
    here by how small this universe and cadence are), same per-key rolling
    cap via `max_entries_per_ticker`.
  * graph-engine/ge/export.py's `append_history()` — the other real
    precedent for "small rotating JSONL log capped at N entries, one line
    per run, not a database" this repo already runs in production for
    `public/data/graph/history.jsonl`.

This log is INTERNAL engine state, like cascade's `state/fund_snapshots.
jsonl` — it lives under `state/`, NOT under `public/data/`, because the
website only ever needs to read the already-computed `revision_direction`/
`revision_pct` fields this module attaches to each exported event; it has
no reason to read the raw snapshot history directly.

HONEST ABSTENTION, exactly like ee/sue.py: `compute_revision()` returns
(direction, pct, reason) where `reason` is non-None if and only if BOTH
`direction` and `pct` are None — never a partial result (e.g. a direction
without a magnitude, or a magnitude without abstaining on a genuinely
undefined case). Never fabricates or interpolates a "prior" value when the
real history does not have one — an absent prior snapshot means an absent
revision read, full stop.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import estimate_snapshots_path

# Below this many total recorded runs for a ticker (this run included), a
# revision read has nothing real to compare against yet — see
# compute_revision()'s docstring for exactly what "recorded runs" counts.
# 2 is the floor by construction (a revision is a comparison between TWO
# points), same role MIN_SURPRISE_QUARTERS_FOR_STDEV plays in ee/sue.py
# for a different honest-abstention floor.
MIN_SNAPSHOTS_FOR_REVISION = 2

# A prior consensus estimate below this (in EPS dollars, absolute value) is
# treated as numerically degenerate as a percent-change DENOMINATOR, not as
# "the company's estimate is remarkably close to zero" — dividing by a
# near-zero prior would manufacture a huge, meaningless percent swing out
# of a small, immaterial absolute change. Same numerical-stability-floor
# technique (and the same value) as ee/sue.py's MIN_USABLE_STDEV, applied
# to a different denominator.
MIN_USABLE_PRIOR_ESTIMATE = 0.005

# How many historical entries to retain per ticker in the rotating log —
# same default cascade-data-engine/cde/export.py's append_fund_snapshots()
# ships with. At most a few runs a day against a 6-name universe, so 180
# entries per ticker is generous multi-month headroom, not a real cap in
# practice.
MAX_ENTRIES_PER_TICKER = 180


def read_snapshots(path: Path | None = None) -> list[dict]:
    """Every recorded (ticker, eps_estimate, as_of_date) line in the log,
    oldest-file-order (not necessarily date-sorted — callers that need
    a specific ticker's history in date order should sort explicitly, as
    `_prior_snapshot` and `compute_and_record_revisions` both do). Missing
    file -> empty list, exactly like cascade's `_read_fund_snapshots` and
    graph-engine's `append_history` both treat a not-yet-created log:
    "no history yet" is a normal, expected first-run state, not an error.
    A line that fails to parse as JSON is skipped rather than raising —
    this is a durable log meant to survive being hand-inspected or
    partially truncated, not a strict-format database."""
    path = path if path is not None else estimate_snapshots_path()
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_snapshots(
    snapshots: list[dict],
    path: Path | None = None,
    max_entries_per_ticker: int = MAX_ENTRIES_PER_TICKER,
) -> Path:
    """Append this run's per-ticker (ticker, eps_estimate, as_of_date)
    snapshots to the rotating log. Mirrors
    cascade-data-engine/cde/export.py's `append_fund_snapshots()` exactly:
    a re-run on the SAME as_of_date REPLACES that ticker's entry for that
    date rather than duplicating it (so re-running this engine several
    times in one day, which is normal — a human re-running it by hand, a
    retry after a transient failure — does not inflate the "how many real
    days of history do we have" count used by compute_revision's
    abstention floor), and each ticker's history is capped at
    `max_entries_per_ticker` most-recent entries so the file never grows
    unbounded."""
    path = path if path is not None else estimate_snapshots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_snapshots(path)
    by_key = {(s["ticker"], s["as_of_date"]): s for s in existing}
    for s in snapshots:
        by_key[(s["ticker"], s["as_of_date"])] = s  # same-day re-run replaces, doesn't duplicate
    by_ticker: dict[str, list[dict]] = {}
    for s in by_key.values():
        by_ticker.setdefault(s["ticker"], []).append(s)
    kept: list[dict] = []
    for ticker, snaps in by_ticker.items():
        snaps.sort(key=lambda s: s["as_of_date"])
        kept.extend(snaps[-max_entries_per_ticker:])
    kept.sort(key=lambda s: (s["ticker"], s["as_of_date"]))
    path.write_text("\n".join(json.dumps(s) for s in kept) + ("\n" if kept else ""))
    return path


def _prior_snapshot(existing: list[dict], ticker: str, before: str) -> dict | None:
    """Most recent snapshot for `ticker` strictly before `before` (an ISO
    date string), or None if there isn't one. Copied from
    cascade-data-engine/cde/export.py's `_prior_snapshot` almost verbatim
    — same semantics, same reason for the strict `<` (a same-day entry is
    THIS run's own prior write, e.g. from an earlier re-run today; it is
    not a second real day of history, so it must not count as one)."""
    candidates = [s for s in existing if s["ticker"] == ticker and s["as_of_date"] < before]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["as_of_date"])


def _history_count(existing: list[dict], ticker: str, before: str) -> int:
    return len([s for s in existing if s["ticker"] == ticker and s["as_of_date"] < before])


def compute_revision(
    current_estimate: float | None,
    prior: dict | None,
    history_count: int,
) -> tuple[str | None, float | None, str | None]:
    """Pure computation, no I/O — same shape/testing rationale as
    ee.sue.compute_sue: dependency-free so it can be unit-tested without
    touching the log file at all.

    `prior` is the ticker's most recent snapshot strictly before this run
    (see `_prior_snapshot`), or None if there isn't one. `history_count` is
    how many such earlier snapshots exist for this ticker (0 on a genuinely
    fresh ticker) — used only to phrase the abstain reason accurately
    ("only N run(s) recorded" counts THIS run as the Nth, matching how a
    human reading the message would count "how many times has this engine
    run for this ticker so far").

    Returns (direction, pct, abstain_reason) where `direction` is one of
    "raised" / "lowered" / "unchanged" and `pct` is a signed percent
    change, OR both are None and `abstain_reason` states plainly why —
    exactly one of {(direction, pct), abstain_reason} is populated, never
    a partial result.
    """
    if current_estimate is None:
        return None, None, "no consensus EPS estimate available for this run — nothing to compare"

    total_runs_including_this_one = history_count + 1
    if prior is None or history_count < MIN_SNAPSHOTS_FOR_REVISION - 1:
        return None, None, (
            f"insufficient snapshot history — only {total_runs_including_this_one} run(s) recorded "
            f"for this ticker, need at least {MIN_SNAPSHOTS_FOR_REVISION}"
        )

    prior_estimate = prior.get("eps_estimate")
    if prior_estimate is None:
        return None, None, (
            f"prior snapshot (as of {prior.get('as_of_date', 'an earlier run')}) had no consensus "
            f"estimate recorded — nothing to compare against"
        )

    if abs(prior_estimate) < MIN_USABLE_PRIOR_ESTIMATE:
        return None, None, (
            f"prior consensus estimate (${prior_estimate:.4f}, as of {prior.get('as_of_date')}) is "
            f"below the numerical-stability floor ({MIN_USABLE_PRIOR_ESTIMATE}) — dividing by it "
            f"would manufacture an outsized percent change from a tiny, immaterial difference"
        )

    pct = (current_estimate - prior_estimate) / abs(prior_estimate) * 100.0
    if current_estimate > prior_estimate:
        direction = "raised"
    elif current_estimate < prior_estimate:
        direction = "lowered"
    else:
        direction = "unchanged"
    return direction, pct, None


def record_and_compute_revisions(
    events: list[dict],
    as_of_date: str,
    path: Path | None = None,
) -> list[dict]:
    """The one function export.py calls. For every event dict in `events`
    (mutated in place, and also returned for convenient chaining): attaches
    `revision_direction` / `revision_pct` / `revision_abstain_reason`
    computed from this ticker's REAL prior snapshots, then appends this
    run's own (ticker, eps_estimate, as_of_date) to the log. Reads the log
    exactly ONCE up front (not per-ticker) — a single small file read, same
    efficiency shape as cascade's `_build_from_live` reading
    `existing_snapshots` once before its per-fund loop."""
    path = path if path is not None else estimate_snapshots_path()
    existing = read_snapshots(path)

    new_snapshots: list[dict] = []
    for event in events:
        ticker = event["ticker"]
        current_estimate = event.get("eps_estimate")

        prior = _prior_snapshot(existing, ticker, as_of_date)
        history_count = _history_count(existing, ticker, as_of_date)
        direction, pct, reason = compute_revision(current_estimate, prior, history_count)

        event["revision_direction"] = direction
        event["revision_pct"] = pct
        event["revision_abstain_reason"] = reason

        new_snapshots.append({"ticker": ticker, "eps_estimate": current_estimate, "as_of_date": as_of_date})

    append_snapshots(new_snapshots, path=path)
    return events
