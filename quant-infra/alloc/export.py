"""Website handoff export for WW-ALLOC — the one JSON the site reads.

Same pattern as `weekly-engine/wf/export.py` / `graph-engine/ge/export.py` /
`chaos-engine/chaos/export.py`: `build_export()` does the work and returns a
dict, `write_export()` writes it to both the web-servable path and an
engine-side copy, `main()` is the CLI entry point.

`quant-infra/alloc/solve.py` had real, tested math (`shrink_edge`,
`score_strategy`, `shrink_covariance`, `solve`) but NO CLI entry point
anywhere — `public/data/alloc/latest.json` was a hand-typed sample fixture
(see its own file: "SAMPLE DATA... one hypothetical solve() call... for
illustration only"), never produced by running code. This module closes that
gap: every number in its output is a genuine `solve()` result — just over a
fabricated, seeded set of inputs, since this sandbox has no persisted
strategy-return history and no live edge feed wired in (see
`src/lib/models/alloc-export.ts`'s own module doc for the same "REAL STATUS
TODAY" framing this export inherits).

The output shape mirrors `src/lib/models/alloc-export.ts`'s `AllocExport`
contract field-for-field — that TypeScript file is the ground truth for the
JSON shape, not this module's own guess at one.

**Honest finding, not a bug**: with a shadow-mode strategy present, `solve()`
in this environment's installed scipy reproducibly falls back
(`fallback_used=True`, `fallback_reason` containing "Singular matrix C in LSQ
subproblem") rather than SLSQP reporting a converged optimum — the redundant
`[0, 0]` bound + literal equality constraint `solve.py`'s own docstring
documents for a shadow-mode variable makes SLSQP's working-set matrix
singular on this scipy build. This is not specific to this export's demo
inputs: it reproduces on `quant-infra/alloc/tests/test_solve.py`'s own
existing `test_shadow_mode_strategy_gets_hard_zero_regardless_of_score`
fixture too (verified by hand while building this module) — that test still
passes because it only asserts the shadow budget is exactly zero and
`"shadow_zero:<name>"` is an active constraint, both of which hold on the
fallback path as designed. So this export's `fallback_used`/
`fallback_reason` fields, when present, are a genuine `solve()` result on
this scipy version, not a fabricated or worked-around one — the fallback
path itself is real and tested, and it still correctly holds the shadow
strategy at a hard zero.

Run:  python3 export.py       (from quant-infra/alloc/)
  or: python3 -m export       (from quant-infra/alloc/, with that directory
                                itself — not quant-infra/ — as the import
                                root; same "each subpackage is its own
                                sealed root" convention as
                                `quant-infra/alloc/tests/test_solve.py`'s own
                                `from solve import ...` bare import)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from solve import SolverConfig, StrategyInput, shrink_covariance, shrink_edge, solve

SCHEMA_VERSION = "0.1.0"
# quant-infra/alloc has no package __version__ constant (its __init__.py is
# empty) — pinned here to match the schema_version generation this export
# format started at. Bump alongside solve.py's own changes.
ENGINE_VERSION = "0.1.0"

DISCLAIMER = (
    "WW-ALLOC is a research capital-allocation model producing budget "
    "recommendations, not executed orders or investment advice. SYNTHETIC-DEMO "
    "DATA: quant-infra/alloc/solve.py is a pure function over caller-supplied "
    "inputs with no persisted strategy-return history and no live edge feed "
    "wired into this sandbox, so the strategies, edges, and budgets below come "
    "from a fabricated, seeded set of StrategyInput records run through the "
    "REAL solve() pipeline (shrink -> score -> solve) — the numbers are a "
    "genuine solver output, computed over made-up inputs, not a live allocation."
)

GENERATED_BY = (
    "WW-ALLOC (synthetic-demo solve() run) — real solve.py pipeline over "
    "fabricated inputs, no live allocator run wired in"
)

DEMO_SEED = 11

# A small, named, plausible set of strategies — same story as the previously
# hand-authored sample fixture (one per other engine this platform has an
# export seam for, plus one shadow-mode candidate), now actually run through
# solve() instead of typed by hand.
#   (name, expected_edge_raw, live_track_record_length, uncertainty, cost_at_size, previous_budget, shadow_mode, cap)
DEMO_STRATEGIES_RAW: list[tuple] = [
    ("Equity L/S (Incepta)",     0.090, 220.0, 0.012, 0.006, 0.26, False, None),
    ("Macro overlay (Aurora)",   0.045, 140.0, 0.018, 0.004, 0.22, False, None),
    ("Intra/Exitus tactical",    0.065,  90.0, 0.030, 0.014, 0.18, False, None),
    ("Weekly rank (WW-WEEKLY)",  0.030, 260.0, 0.020, 0.006, 0.15, False, None),
    ("Dispersion overlay (new)", 0.070,  15.0, 0.040, 0.020, 0.00, True,  None),
]


def _synthetic_strategy_returns(n_strategies: int, n_obs: int = 250, seed: int = DEMO_SEED) -> np.ndarray:
    """A deterministic, seeded (T x N) daily-return-like panel for the demo
    strategies, correlated through one shared factor (same "one market factor
    + idiosyncratic noise" construction used elsewhere in this repo's
    synthetic-demo generators, e.g. `engine/tests/test_state.py`'s synthetic
    universe) — just enough structure for `shrink_covariance`'s Ledoit-Wolf
    fit to produce a genuine, non-degenerate covariance matrix rather than a
    trivial diagonal one."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 0.01, n_obs)
    idio = rng.normal(0.0, 0.015, (n_obs, n_strategies))
    betas = rng.uniform(0.2, 0.8, n_strategies)
    return factor[:, None] * betas[None, :] + idio


def build_export(cfg: SolverConfig | None = None) -> dict:
    cfg = cfg or SolverConfig(turnover_penalty=0.25)

    strategies = [
        StrategyInput(
            name=name,
            expected_edge_raw=edge,
            live_track_record_length=n_obs,
            uncertainty=unc,
            cost_at_size=cost,
            previous_budget=prev,
            shadow_mode=shadow,
            cap=cap,
        )
        for (name, edge, n_obs, unc, cost, prev, shadow, cap) in DEMO_STRATEGIES_RAW
    ]

    returns = _synthetic_strategy_returns(len(strategies))
    cov = shrink_covariance(returns)
    log = solve(strategies, cov, cfg)

    strategy_results = []
    for s in strategies:
        shrunk = shrink_edge(s.expected_edge_raw, s.live_track_record_length, cfg.prior_pseudo_obs)
        uncertainty_term = cfg.uncertainty_penalty * s.uncertainty
        cost_term = cfg.cost_penalty * s.cost_at_size
        budget = log.solution[s.name]
        prev_budget = log.previous_budget[s.name]
        # Entries in SolveLog.active_constraints are "<kind>:<name>" — a
        # simple suffix match pulls out exactly the ones naming this
        # strategy, matching alloc-export.ts's documented per-row semantics.
        binding = [c for c in log.active_constraints if c.endswith(f":{s.name}")]
        score = log.scores[s.name]
        strategy_results.append(
            {
                "name": s.name,
                "shrunk_edge": round(float(shrunk), 6),
                "uncertainty_penalty_term": round(float(uncertainty_term), 6),
                "cost_penalty_term": round(float(cost_term), 6),
                # The demo inputs are all finite/non-negative by construction
                # (see DEMO_STRATEGIES_RAW), so solve() never NaNs a score
                # here — round() is always safe. A real deployment feeding
                # solve() malformed inputs could still NaN a score; that case
                # is intentionally not modelled by this synthetic-demo export.
                "score": round(float(score), 6),
                "previous_budget": round(float(prev_budget), 6),
                "budget": round(float(budget), 6),
                "delta": round(float(budget - prev_budget), 6),
                "shadow_mode": s.shadow_mode,
                "binding_constraints": binding,
            }
        )

    as_of = date.today().isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "config": {
            "prior_pseudo_obs": cfg.prior_pseudo_obs,
            "uncertainty_penalty": cfg.uncertainty_penalty,
            "cost_penalty": cfg.cost_penalty,
            "risk_aversion": cfg.risk_aversion,
            "turnover_penalty": cfg.turnover_penalty,
            "default_cap": cfg.default_cap,
            "total_gross_limit": cfg.total_gross_limit,
            "max_step_fraction": cfg.max_step_fraction,
        },
        "strategies": strategy_results,
        "active_constraints": list(log.active_constraints),
        "fallback_used": log.fallback_used,
        "fallback_reason": log.fallback_reason,
        "feasible": log.feasible,
        "objective_value": None if log.objective_value is None else round(float(log.objective_value), 6),
        "disclaimer": DISCLAIMER,
        "generatedBy": GENERATED_BY,
    }


def default_export_paths() -> list[Path]:
    alloc_dir = Path(__file__).resolve().parent          # quant-infra/alloc/
    repo_root = alloc_dir.parent.parent                  # WhiteWaterCapital-main/
    return [
        repo_root / "public" / "data" / "alloc" / "latest.json",  # web-servable
        alloc_dir / "exports" / "latest.json",                     # engine-side copy
    ]


def write_export(payload: dict, paths: list[Path] | None = None) -> list[Path]:
    """Write `payload` to `paths` (default: the real website + engine-copy
    locations, see `default_export_paths`). Tests should pass their own
    `paths` (e.g. a temp directory) so running the test suite never
    overwrites the real handoff file."""
    paths = paths if paths is not None else default_export_paths()
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    print(f"Exported {len(payload['strategies'])} strategies (as of {payload['as_of']}, synthetic-demo).")
    print(
        f"  feasible={payload['feasible']} fallback_used={payload['fallback_used']} "
        f"objective_value={payload['objective_value']}"
    )
    for s in payload["strategies"]:
        print(f"    {s['name']:<28} budget={s['budget']:.3f} (prev {s['previous_budget']:.3f}, delta {s['delta']:+.3f})")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
