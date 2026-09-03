# WW-LABEL — the label engine (FEAT-02)

A **sealed labeling package**: forward-return labels, triple-barrier labels,
sample-uniqueness weights, meta-labeling, and one non-negotiable look-ahead
assertion. Straight from the FEAT-02 spec's own reasoning for why this is a
separate component rather than logic living inside each model: *"Labels are
where look ahead gets in, so they get their own component and their own
tests rather than living inside each model."*

This engine is its own world. It shares **no code and no state** with
`../engine` (Incepta), `../weekly-engine`, `../graph-engine`,
`../feature-store` (FEAT-01, built alongside this in the same pass by a
different agent), or any other component in this repo — per this repo's
"sealed engine" convention, it communicates only through its own plain
function API (`lbl.forward_return_labels(...)`,
`lbl.assert_no_lookahead(...)`, etc.), never through shared state, a shared
database, or an import into/from another engine's package. It writes no
export JSON and is not wired into `src/lib/models/registry.ts` or any page —
this package is a pure Python labeling library, nothing more.

## Design

Five independent primitives, each in its own module:

1. **`lbl/forward_return.py`** — the label for period *t* is the return from
   close of period *t* to close of period *t+horizon*, and every label this
   module produces is returned paired with a `knowable_from` timestamp — the
   actual timestamp of the *t+horizon* close itself, not a fixed calendar
   offset (so an irregular calendar, e.g. a holiday-shortened week, cannot
   silently understate how late the label really becomes knowable). There is
   deliberately no function anywhere in this package that hands back a bare
   numeric label — the whole point of FEAT-02 is that a label without a
   knowable-from time is exactly how look-ahead gets in.

2. **`lbl/triple_barrier.py`** — the López de Prado triple-barrier method for
   short-horizon models. Three barriers (upper, lower, time) are set around
   an entry price, sized by a **trailing** volatility estimate computed
   *only* from data at or before the entry time (never the future), and the
   price path is walked forward until one of the three is touched. Label
   convention (documented in the module, since more than one is reasonable):
   `+1` upper touched first, `-1` lower touched first, `0` on a timeout. The
   realized return to the actual touch is also returned on every record, for
   callers who want a continuous target instead of the discrete one.

3. **`lbl/uniqueness.py`** — average-uniqueness sample weights. A label's
   window (`[start, end]`) overlapping another label's window means the two
   are not independent observations of the market — they are graded, in
   part, on the very same price move. This computes, bar by bar on the
   caller-supplied common time grid, how many labels' windows are "live"
   (concurrency); each live label earns `1/concurrency` credit for that bar;
   a label's weight is the average of its own credit over its own window.
   Verified by construction: non-overlapping windows get exactly `1.0`,
   fully coincident windows split credit exactly in half (`0.5` each), and
   partial overlaps land strictly between the two, all hand-computed in
   `tests/test_uniqueness.py`.

4. **`lbl/meta_label.py`** — the secondary "should I act on the primary
   signal" target. The training set is built from **only** the rows where
   the primary model actually fired (`direction != 0`, or an explicit
   `fired` mask) — non-firing rows are dropped from the frame entirely, not
   kept with a placeholder label, because there is no action to grade on
   them. `meta_label = 1` iff the sign of the primary direction matches the
   sign of the realized outcome; a realized outcome of exactly zero never
   matches a nonzero direction, so a net-zero result reads as "not
   profitable" rather than getting a free pass.

5. **`lbl/lookahead_assert.py`** — `assert_no_lookahead(labels, features)`.
   Raises `LookAheadError` (never warns, never logs-and-continues) if any
   feature's `as_of` timestamp is not strictly earlier than the paired
   label's `knowable_from` timestamp. Read the function signature: there is
   no `strict=`, no `enabled=`, no config object, no env-var escape hatch —
   nothing to flip in a config file to weaken or skip this check. The only
   way it does not run on a given training path is if that path never calls
   it, which is a visible, reviewable line (or its absence), not a setting.

## What "done" means here, and what is deliberately not done

Per the FEAT-02 "done when" bar — *"the assertion sits in the training path
and sample weights are non uniform wherever label windows overlap"* — this
pass delivers:

- `assert_no_lookahead` exists, is unconditional, and is proven (in
  `tests/test_lookahead_assert.py`) to both raise on a deliberately leaky
  pairing and pass cleanly on a correctly aligned one, including an
  end-to-end version built on this package's own `forward_return_labels`.
- `average_uniqueness_weights` is proven (in `tests/test_uniqueness.py`) to
  produce weights strictly less than 1.0 wherever windows overlap, and
  exactly 1.0 where they don't.

What is **not** done in this pass, on purpose:

- **Wiring into an actual training loop.** `assert_no_lookahead` is not
  currently called from `weekly-engine`'s or `chaos-engine`'s training path,
  and this package's labels are not fed into either engine's feature panel.
  This package is a standalone library; making any consumer call it on every
  training run is the integration step, tracked as future work, not part of
  this pass.
- **Wiring to `feature-store` (FEAT-01).** `feature-store` produces features
  with their own `as_of`/point-in-time timestamps (built alongside this
  package by a separate agent in this same pass); `assert_no_lookahead`'s
  `features` argument is shaped to accept exactly that (a DataFrame with an
  `as_of` column, or a raw timestamp sequence), but no code in either
  package currently imports the other. Wiring them together — pulling
  feature-store's per-row `as_of` values and this package's per-row
  `knowable_from` values into one paired call to `assert_no_lookahead` on
  every training run — is the natural next step and is intentionally left
  undone here, consistent with the sealed-engine convention: no engine
  reaches into another's internals; a future integration pass would add a
  thin adapter, not a direct import between the two packages.
- **No real price/signal data adapter.** Every test in this package builds
  its own small, deterministic, hand-constructed price/signal series inline
  — there is no synthetic-universe generator or live data adapter here (this
  package does not need one to do its job; it operates on whatever price or
  signal series a caller hands it).
- **Triple-barrier's same-bar tie-break is a documented convention, not an
  intrabar-path fact.** With a close-only price series, a single bar that
  gaps past both barriers has to be resolved somehow; `triple_barrier.py`
  picks whichever barrier the close overshot by more (ties go to upper) and
  says so in its docstring, rather than claiming to know the true intrabar
  order of events (which a close-only series cannot know). This never
  triggers in the shipped tests, which are constructed to hit one barrier
  cleanly.

## Layout

```
label-engine/
  lbl/
    __init__.py            # public API surface
    forward_return.py       # forward-return label + knowable_from
    triple_barrier.py       # upper/lower/time barrier walk, vol-scaled, PIT-safe
    uniqueness.py           # average-uniqueness sample weights
    meta_label.py           # primary-fired-only meta-labeling training set
    lookahead_assert.py     # the hard, undisable-by-config look-ahead assertion
  tests/                   # pytest-style; run via _pyshim/run_tests.py in this sandbox
    test_forward_return.py
    test_triple_barrier.py
    test_uniqueness.py
    test_meta_label.py
    test_lookahead_assert.py   # the FEAT-02 core acceptance test
  requirements.txt
  pytest.ini
```

## Running the tests

This sandbox has no PyPI access, so there is no real `pytest` installed —
same offline shim used by `weekly-engine` and `graph-engine`:

```bash
cd label-engine
python3 /home/claude/repo/_pyshim/run_tests.py "$(pwd)" tests   # offline pytest-shim
```

In a real environment with `pip install -r requirements.txt` available,
`pytest -q` from this directory runs the same suite.

**Current result: 35 passed, 0 failed, 0 skipped (5 test files).**
