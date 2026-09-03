# `decision/` — WW-DECISION (IMP-19)

Keeps the decision-engine/allocator boundary in the code's actual shape,
not just in comments, plus the v1.0 fallback path and a reproducibility
record.

- **`idea.py`** — `DecisionOutput` (`is_good_idea: bool | None`,
  `confidence: float` in `[0, 1]`, `rationale: str`). Deliberately has
  **no** sizing/weight/budget/capital field — enforced by a test
  (`tests/test_idea.py::test_no_sizing_or_capital_fields_exist_on_decision_output`)
  that inspects the dataclass's actual fields, not just its docstring.
- **`reliability_fallback.py`** — `fixed_weight_fallback(strategy_reliabilities,
  shrinkage)`: the v1.0 path. Shrinks each reliability score toward the
  mean of all reliability scores by `shrinkage`, then normalises to sum to
  1. `shrinkage=0.0` tracks raw reliabilities (normalised); `shrinkage=1.0`
  is a direct special case returning `1/n` for every strategy regardless
  of the raw scores (handled specially so an all-zero-reliability input
  still produces a well-defined equal weighting instead of a `0/0`
  degeneracy). Has no dependency on the allocator.
- **`boundary.py`** — `get_strategy_weights(allocator_solve_fn,
  strategy_reliabilities, fallback_shrinkage=...)`: calls the injected,
  zero-argument `allocator_solve_fn`; falls back to
  `fixed_weight_fallback` and sets `alarm_raised=True` with a written
  `reason` if it raises, if the returned result reports `feasible=False`,
  or if the result doesn't expose the expected `solution`/`feasible`
  shape (attribute- or dict-style) or contains a non-finite weight. This
  is the literal "disabling the allocator degrades us to v1.0 behaviour
  with no code change and no outage" mechanism.
- **`reproducibility.py`** — `build_decision_replay_record(decision_output,
  allocator_inputs, boundary_result)` packages all three into one plain,
  JSON-serialisable dict for later replay/audit.

Run tests:

```bash
python3 /home/claude/repo/_pyshim/run_tests.py <abs>/quant-infra/decision tests
```

## Deviations / scope notes

- `boundary.py` deliberately does **not** import `alloc/solve.py` at
  module scope — `allocator_solve_fn` is an injected zero-argument
  callable so this package stays decoupled and testable with bare stubs.
  `tests/test_boundary.py` does import `alloc/solve.py` (read-only, for
  two integration tests: a real success path and a real infeasible-cap
  fallback path) by inserting `quant-infra/alloc` onto `sys.path` inside
  the test file — the same "sealed root" convention every `quant-infra/*`
  subpackage's tests already use for imports within their own package,
  extended here to reach across the one read-only dependency this task
  explicitly allowed.
- **Documented gap: the allocator-result contract is checked, not
  enforced by a shared type.** `boundary.py`'s "does this look like a
  `SolveLog`" check (`feasible` + `solution`, attribute or dict access) has
  only been exercised against the specific `alloc/solve.py` that exists in
  this repo today (via the integration tests) and against hand-built stub
  objects/dicts. If `alloc/solve.py`'s `SolveLog` shape changes in a way
  that removes or renames either field, `boundary.py` will treat every
  real solve as "malformed" and permanently fall back (safely — the
  fallback path is safe by construction — but noisily, since every call
  would raise the alarm). This is the intended fail-safe behaviour per the
  doc ("no outage"), but it means a `SolveLog` shape change should update
  this module's contract check too, not rely on it degrading silently.
- **Documented gap: `reproducibility.py` builds the record; it does not
  persist it.** Actually writing the record to a store (a database, an
  append-only ledger analogous to `sizing/ledger.py`) is out of scope for
  this pass — wiring it to a real store is future work.
