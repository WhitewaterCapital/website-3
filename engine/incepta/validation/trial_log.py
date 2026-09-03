"""MLVAL-02 — trial logging.

"Log every configuration tested including the abandoned ones. The trial count
is needed to deflate the result and cannot be reconstructed afterwards ...
the harness will not emit a raw figure without its deflated counterpart."

This module does NOT reimplement the deflation math — that already lives in
`validation/metrics.py` (`deflated_sharpe_ratio`) and is imported here. What
was missing was the append-only record of every trial (so `n_trials` is a
real count read back from a log, not a number someone remembers) and a
reporting path that refuses to hand back a raw Sharpe on its own.

Storage goes through the small `RecordStore` seam in `store.py` so it can
later be swapped for Supabase without any caller (this module's own
functions, or whatever calls them) changing. The default implementation is a
local JSON-lines file per `model_id` under `engine/incepta/_trials/`
(gitignored — these are local research artifacts, not audited records).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .metrics import deflated_sharpe_ratio
from .store import JsonlRecordStore, RecordStore

_DEFAULT_BASE_DIR = Path(__file__).resolve().parents[1] / "_trials"


def default_store() -> RecordStore:
    """The default trial store: local JSON-lines files under
    `engine/incepta/_trials/` (created on first use)."""
    return JsonlRecordStore(_DEFAULT_BASE_DIR)


def log_trial(
    model_id: str,
    config: dict,
    raw_sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
    store: Optional[RecordStore] = None,
) -> dict:
    """Append ONE trial — successful or abandoned — to the log for
    `model_id`, and compute+store its Deflated Sharpe Ratio in the same
    record. `n_trials` is the RUNNING count read back from the log (every
    prior trial for this `model_id`, plus this one) — never a number supplied
    by the caller, so it can't be understated by forgetting an abandoned run.

    `raw_sharpe` must be the per-observation (NOT annualized) Sharpe — the
    same convention `validation.metrics.deflated_sharpe_ratio`'s `sr`
    argument uses.

    `sr_variance_across_trials` (required by the deflation formula) is the
    sample variance of the raw Sharpes actually observed across every trial
    logged for this `model_id` so far, including this one — i.e. it too comes
    from the log, not from an assumption.
    """
    store = store or default_store()
    prior = store.list(model_id)
    n_trials = len(prior) + 1
    sharpes = [r["raw_sharpe"] for r in prior] + [raw_sharpe]
    sr_variance = float(np.var(sharpes, ddof=1)) if len(sharpes) >= 2 else 0.0

    dsr = deflated_sharpe_ratio(
        sr=raw_sharpe,
        n_obs=n_obs,
        n_trials=n_trials,
        sr_variance_across_trials=sr_variance,
        skew=skew,
        kurt=kurt,
    )

    record = {
        "model_id": model_id,
        "trial_index": n_trials,
        "config": config,
        "raw_sharpe": raw_sharpe,
        "n_obs": n_obs,
        "skew": skew,
        "kurt": kurt,
        "n_trials_at_log_time": n_trials,
        "sr_variance_across_trials": sr_variance,
        "deflated_sharpe_ratio": dsr,
        "logged_at": datetime.now().isoformat(),
    }
    store.append(model_id, record)
    return record


def report(
    model_id: str,
    *,
    store: Optional[RecordStore] = None,
    raw_only: bool = False,
) -> list[dict]:
    """The full trial history for `model_id`. Every record carries
    `raw_sharpe` paired with its `deflated_sharpe_ratio` — that pairing is
    what makes a Sharpe figure honest here, and this function refuses to
    break it apart:

    - `raw_only=True` is refused outright (RuntimeError) — there is no
      supported way to ask this function for a raw-only figure.
    - Even with the default call, if a record in the log somehow carries
      `raw_sharpe` without a `deflated_sharpe_ratio` (a corrupted or
      hand-edited log file — `log_trial` never writes one that way), this
      refuses rather than silently reporting the naked number.
    """
    if raw_only:
        raise RuntimeError(
            "Refused: report() will not emit a raw Sharpe without its "
            "deflated counterpart. The trial count needed to deflate a result "
            "cannot be reconstructed after the fact, so raw-only reporting is "
            "disabled. Call report(model_id) (without raw_only) to get "
            "raw_sharpe paired with deflated_sharpe_ratio."
        )

    store = store or default_store()
    records = store.list(model_id)
    if not records:
        raise LookupError(f"no trials logged for model_id={model_id!r}")

    for r in records:
        if "raw_sharpe" in r and "deflated_sharpe_ratio" not in r:
            raise RuntimeError(
                f"Refused: a trial record for {model_id!r} carries raw_sharpe "
                "with no deflated_sharpe_ratio counterpart — the log is "
                "corrupted or was written by non-conforming code. Not "
                "reporting a raw figure without its deflated counterpart."
            )
    return records
