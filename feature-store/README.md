# feature-store (FEAT-01)

The one place a feature gets defined, computed in batch, and served live —
so that no two models in this codebase can silently drift apart on what a
name like `ret_lag_5` or `rsi_14` actually means.

## Why this exists

Straight from the requirements doc:

> "Came from the brief asking that all models intertwine. They cannot
> share anything safely without one place where features are defined.
> This is the highest leverage piece of infrastructure in Part II and the
> one that gets skipped."

Every other engine in this repo (`weekly-engine`, `graph-engine`,
`path-engine`, `engine`, ...) currently defines its own features inline,
independently. That's fine in isolation, but the moment two models are
meant to intertwine — share a signal, be trained on the same panel, be
validated against each other — a feature computed twice is a feature that
can silently diverge. `feature-store` is new, standalone infrastructure
built to stop that from happening *the next time* a feature needs to be
shared, not a retrofit of any existing engine's features. **Nothing in
this repo imports it yet** — this pass builds and proves the mechanism
only (see "What's a demo vs. what's real" below).

## Design

```
feature-store/
  fs/
    registry.py           FeatureDef, FeatureRegistry -- name, version,
                           owner, lookback, rationale, missing-data policy,
                           and the one `compute` function. No rationale,
                           no registration (enforced at construction time).
    missing_data.py        apply_missing_data_policy() -- the ONE place a
                           policy (forward_fill_max_age / treat_as_missing
                           / fail) is applied. Never fills with 0.
    panel.py                build_panel() -- the batch job. Dated table
                           indexed by (security, date), one column per
                           feature. Calls each FeatureDef's own `compute`,
                           never a re-derivation of it.
    live.py                  compute_live_feature() / compute_live_cross_sectional()
                           -- the serving path. Calls the EXACT SAME
                           `FeatureDef.compute` object build_panel() calls,
                           truncated to "as of now".
    cross_sectional.py        rank / zscore_within_universe /
                           zscore_within_sector, each its own registered
                           FeatureDef built on top of a base feature's
                           already-computed column -- not a helper method
                           bolted onto the base feature.
    manifest.py                build_manifest() / manifest_hash() /
                           manifest_changed() -- what a model artifact
                           records about the feature set it trained
                           against.
    sample_features.py          A small SAMPLE/DEMO feature set (lagged
                           returns, RSI, realized vol) proving the
                           mechanics end to end. NOT a production feature
                           set.
    synthetic.py                 Deterministic SAMPLE OHLCV generator, used
                           only by this package's own tests.
  tests/                        pytest-style; run via _pyshim/run_tests.py
                           in this sandbox (see "Running the tests" below).
```

### The one invariant everything else is built to preserve

A registered `FeatureDef.compute` is a **pure, non-anticipative** function
of the point-in-time data it's handed: `compute(df)` returns a value/Series
whose entry at date `t` never changes if rows dated after `t` are appended
to `df`. Given that single invariant:

- **Batch** (`panel.build_panel`) computes `compute()` once over a
  security's whole available history and reads off whichever dates were
  requested.
- **Live** (`live.compute_live_feature`) truncates a security's history to
  `as_of` and calls the *same* `compute()`, reading off the last row.

Because both call the literal same Python function object — never two
copies of "the same" math — batch and live can only disagree if a
registered `compute()` breaks the non-anticipative invariant. That is
exactly what `tests/test_batch_live_parity.py` checks, both by comparing
batch panel values against live-served values directly, and by asserting
directly that appending future rows never changes a past value for every
registered feature. This is the FEAT-01 acceptance test: *"batch and live
produce identical values for the same timestamp."*

The same logic extends to the cross-sectional layer: a cross-sectional
`FeatureDef.compute` is a pure function of a single date's cross-section
(one row per security), and `cross_sectional.add_cross_sectional_column`
(batch) / `live.compute_live_cross_sectional` (serving) both call it
directly.

### Missing data, never zero

Every `FeatureDef` declares exactly one of three policies:

| Policy | Behavior |
|---|---|
| `treat_as_missing` | NaN passes through unchanged. Consumers must handle it explicitly. |
| `fail` | Any NaN in the computed output raises `MissingDataFailure` — this feature must never silently reach a model with a gap in it. |
| `forward_fill_max_age` | Forward-fills from the last valid observation, capped at `max_age_periods` consecutive periods. A gap older than that stays NaN. |

`apply_missing_data_policy` (in `missing_data.py`) never calls `.fillna(0)`
or passes a `fill_value` under any policy. Zero is a real, meaningful value
for a feature like a return or a z-score — collapsing "missing" into
"zero" would silently corrupt every downstream consumer's math, which is
exactly the failure mode the spec calls out by name.

### Manifest hashing

`manifest.manifest_hash(feature_defs)` is a sha256 over a sorted, canonical
`(name, version)` list — stable across process restarts and registration
order, and it changes if and only if the feature set itself changes (a
feature added, dropped, or version-bumped). It deliberately ignores
`owner`, `rationale`, `lookback`, and the `compute` function's identity:
renaming an owner or clarifying a rationale should not force a retrain;
changing what a feature actually computes (signaled by a version bump)
should. `manifest_changed(old_hash, new_hash)` is the helper a training
pipeline calls before serving a model — a falsy `old_hash` (no prior run
recorded) always counts as "changed," so the safe default is retrain-
before-first-serve, not assume-it's-fine.

**This is a proof of the mechanism, not a wired-up training pipeline.**
No model artifact schema exists yet in this repo to attach a manifest hash
to (that lives with whichever training pipeline eventually consumes this
store) — `manifest_hash`/`manifest_changed` are ready to be called by one.

## What's a demo vs. what's real

**Real, general-purpose infrastructure:**
- `fs/registry.py`, `fs/missing_data.py`, `fs/panel.py`, `fs/live.py`,
  `fs/cross_sectional.py`, `fs/manifest.py` — none of these know or care
  what a "feature" actually is; they'd work identically for a completely
  different feature set.

**Sample / proof-of-concept, explicitly NOT production:**
- `fs/sample_features.py` registers five mechanical, well-understood
  features (`ret_lag_1/5/10`, `rsi_14`, `realized_vol_20`) purely to
  exercise the store end to end, plus three cross-sectional transforms
  (`ret_lag_5_rank`, `ret_lag_5_zscore_universe`, `ret_lag_5_zscore_sector`)
  built on top of one of them.
- `fs/synthetic.py` generates deterministic, clearly-labeled SAMPLE OHLCV
  data (fixed-seed geometric random walk) used only in this package's own
  tests. **No real market data is used anywhere in this package**, and no
  economic claim is made about any value these sample features produce
  beyond "this is what the formula returns on made-up numbers."

Real production feature definitions — news, positioning, fundamentals,
factor exposures, and everything else this platform's models will
eventually want to share through this store — are **blocked pending the
real data feeds** described elsewhere in this project's requirements
(DATA-01/02/03, IMP-10 through IMP-14). Wiring an actual model or engine
to consume this store, and wiring a real `load_history` callback to a real
point-in-time data source, are both out of scope for this pass.

## Running the tests

This sandbox has no `pytest` installed and no network access. Tests run
through the repo's shared offline pytest-compatible shim, exactly like
every other Python package in this repo (`weekly-engine`, `data-router`,
`quant-infra`, ...):

```bash
python3 /home/claude/repo/_pyshim/run_tests.py /home/claude/repo/WhiteWaterCapital-main/feature-store tests
```

## Deviations from the literal spec, and why

- **Two extra `FeatureDef` fields beyond the spec's literal list**:
  `kind` (`"per_security"` or `"cross_sectional"`) and `base_feature`
  (the `(name, version)` a cross-sectional transform was built on). These
  exist because a cross-sectional feature's `compute` has a genuinely
  different signature (a single date's cross-section of securities, not
  one security's time series) — `kind` is what lets `panel.py` and
  `live.py` route each `FeatureDef` to the right computation path, and
  `base_feature` is documentation the manifest can (in principle) surface.
  Neither changes the spec's required fields; both are additive.
- **`forward_fill_max_age` is rejected for `kind="cross_sectional"`
  features** (enforced at registration time). "Maximum age" is a
  statement about a time axis, and a cross-sectional feature's `compute`
  only ever sees a single date's snapshot — there is no time axis to age
  against within it. This wasn't spelled out in the spec; it's a
  consequence of taking "declares a missing data policy" seriously for a
  feature kind the spec's examples don't explicitly cover.
- **`build_panel` requires every requested date to already exist in a
  security's history index** (raises otherwise), rather than silently
  introducing new NaN rows for dates the loader's calendar doesn't have at
  all. This closes a gap where a `"fail"`-policy feature's raise-on-NaN
  check could otherwise be bypassed by requesting a date that simply isn't
  in the input calendar.

## Documented gaps (left for a future pass, not silently skipped)

- No real vendor/data connection of any kind — `load_history` is a
  caller-supplied callback in this pass, matching the instruction not to
  invent a broker/vendor connection.
- No wiring into any existing engine or into the Next.js site. This is a
  standalone package; adopting it in `weekly-engine`/`graph-engine`/etc.,
  or building a model-artifact schema that actually records
  `manifest_hash`, is future work.
- `panel.build_panel` computes each per-security feature's full series in
  one call per security (not chunked/streamed) — fine for this sandbox's
  data volumes, not evaluated for a production-scale universe/date range.
- Cross-sectional transforms here are demonstrated on exactly one base
  feature (`ret_lag_5`); nothing prevents registering them against any
  other `per_security` feature, but only the one is wired up in
  `sample_features.py`.
