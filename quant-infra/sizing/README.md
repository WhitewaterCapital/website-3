# `sizing/` — WW-SIZING (IMP-17)

Allocator budget as the ceiling on position size, plus an append-only log
of which ceiling bound.

- **`ceiling.py`** — `resolve_position_size(allocator_budget, portfolio_risk_ceiling)`
  returns a `SizingDecision`: `approved_size` is `min(allocator_budget,
  portfolio_risk_ceiling)`, except an `allocator_budget` of exactly `0.0`
  forces `approved_size = 0.0` regardless of how large
  `portfolio_risk_ceiling` is (`binding_constraint = "zero_budget"`).
  Otherwise `binding_constraint` is `"allocator"`, `"portfolio_risk"`, or
  `"both_equal"`. The dataclass carries a fixed `note` field documenting
  that **this module does not gate research or analysis output** — a
  strategy sized to zero can and should still publish research; only
  position sizing is affected.
- **`ledger.py`** — an append-only sizing-decision ledger recording every
  `SizingDecision` with a strategy id and timestamp, so the binding
  constraint is identifiable after the fact. `InMemorySizingLedger` for
  tests/short-lived callers; `JsonlSizingLedger` (one `<strategy_id>.jsonl`
  file per strategy, append-mode) for a real on-disk trail — mirrors the
  style of `engine/incepta/validation/store.py`'s `JsonlRecordStore` but is
  a self-contained implementation local to this package (this is a sealed
  root, same as every other `quant-infra/*` subpackage — it does not
  import from `engine/`).

Run tests:

```bash
python3 /home/claude/repo/_pyshim/run_tests.py <abs>/quant-infra/sizing tests
```

## Deviations / scope notes

- No deviations from the spec's stated interface.
- Wiring `resolve_position_size`'s two inputs to the *real* allocator
  budget (`quant-infra/alloc/solve.py`'s `SolveLog.solution[strategy]`) and
  a real portfolio-risk engine is out of scope here — this package accepts
  both numbers as plain floats from whatever caller has already computed
  them.
