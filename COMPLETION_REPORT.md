# WhiteWater Capital — Website + Models: Completion Report

**Scope of this report:** every checklist item under the Notion doc's "Website + Models" header (Part 1: IMP-01 through IMP-21; Part 2: DATA-01/02/03, FEAT-01/02, WKLY-01, CHAOS-01/02/03, GRAPH-01, CASC-01, STATE-01, ALLOC-01, LOOP-01/02/03/04, ORCH-01, VIS-01, VIBE-01, MLVAL-01/02/03/04, WATCH-01/02/03, PATH-01 through PATH-07).

**How to read this report:** every item is marked **Done**, **Partial**, or **Blocked**. "Done" means the code exists, is tested, and I independently re-ran its tests myself rather than trusting a subagent's self-report. "Partial" means real, working infrastructure exists but doesn't fully satisfy the ticket's stated "done when" criterion — the gap is named explicitly. "Blocked" means the item genuinely cannot be built further in this environment, and the specific missing dependency (a vendor API key, network access to install a package, a file that was never provided, a live database, real user accounts) is named. Nothing on this list was silently dropped.

**Test tally, independently re-run and confirmed by me (not just reported by the agents that wrote them):**

| Package | Tests | Status |
|---|---|---|
| `engine/` (Incepta equity + validation, incl. new `calibration.py`) | 69 | all passing |
| `intra-exitus-engine/` | 82 | all passing |
| `graph-engine/` (WW-GRAPH) | 71 | all passing |
| `weekly-engine/` (WW-WEEKLY) | 48 | all passing |
| `chaos-engine/` (WW-CHAOS) | 45 | all passing |
| `path-engine/` (WW-PATH) | 77 | all passing |
| `data-router/` (DATA-01/02) | 117 | all passing |
| `feature-store/` (FEAT-01) | 45 | all passing |
| `label-engine/` (FEAT-02) | 35 | all passing |
| `quant-infra/alloc/` (WW-ALLOC) | 28 | all passing |
| `quant-infra/cascade/` (WW-CASCADE) | 34 | all passing |
| `quant-infra/loop/` (self-improvement loop) | 46 | all passing |
| `quant-infra/orch/` (scheduler + three clocks) | 62 | all passing |
| `quant-infra/sizing/` (IMP-17) | 15 | all passing |
| `quant-infra/cost/` (IMP-18) | 31 | all passing |
| `quant-infra/decision/` (IMP-19) | 25 | all passing |
| **Python total** | **830** | **all passing** |
| Node verification scripts (roles/audit, macro contract, regime vector, conviction) | 117 checks | all passing |

TypeScript/TSX cannot be compiled in this sandbox (no network to install `node_modules`/`@types/*`); every batch of website changes went through a dedicated manual line-by-line review pass standing in for `tsc`/`next build`, cross-checking every import against real exports and every prop against real component interfaces. Confidence from those reviews: **High** that the site compiles cleanly once `npm install` is run somewhere with network access.

---

## Part 1 — Improving existing stuff

| ID | Status | Notes |
|---|---|---|
| IMP-01 | **Done** | `/performance` page: per-strategy attribution table next to period weight, a stacked-area weight-history chart on the same time axis as the equity curve, discretionary/model/paper kept as three separate lines, all v1.0 disclosures kept. |
| IMP-02 | **Partial** | The visual layer (VIS-01) has static/replay modes, honest "stale" badges with a visible timestamp instead of a frozen chart, and color-plus-shape/word encoding throughout. Not done: no automated accessibility audit (axe/Lighthouse) was actually run, and no real first-paint/main-thread budget was measured on a device — this sandbox has no browser or network access to run either. The mechanism is built; the acceptance numbers are unverified. |
| IMP-03 | **Partial / Blocked** | `src/lib/roles.ts` + `src/lib/audit.ts`: a full, tested authorization model — research-operator vs. risk-approver permission table, a hard `assertCanPerform` guard, two-distinct-named-approver enforcement on promotion, and an append-only audit log with no update/delete method on its own type (36 checks, all passing). **Genuinely blocked**: none of this is wired into any page or API route, because `src/lib/auth.ts` is an explicitly-flagged shared-passcode placeholder — there is no real per-person login anywhere in this codebase today. Wiring needs a real auth provider (Clerk / Auth.js / Supabase Auth) with real credentials this environment does not have. |
| IMP-04 | **Done** | `/watch` position detail: originating strategy, allocator weight at entry, score components at entry, forecast + horizon, invalidation traffic light shared with WATCH-01, link to the decision ledger entry and model version. |
| IMP-05 | **Done** | Dashboard allocator panel: budget/previous/delta per strategy, edge/uncertainty/cost decomposition, market state in plain words (reused from WW-STATE's own renderer), manual override with a required written reason and a real auto-reverting timer (UI-only — see gap below). |
| IMP-06 | **Done** | `macro-contract-v2.ts`: versioned, explicitly nullable schema with a new regime block; `/api/macro/latest` and `/api/macro/point-in-time` endpoints. **Named caveat**: the point-in-time endpoint's history is four small, clearly-labeled synthetic fixture snapshots — there is no real historical macro archive in this environment (the real Aurora engine's history lives in a separate repo never provided here). The lookup mechanism itself (nearest-at-or-before, deterministic, honest 404 rather than a silent fallback to "latest") is real and tested. |
| IMP-07 | **Done** (mechanism) | `quant-infra/orch/` scheduler (dependency graph, per-job stale-input policy, per-tier concurrency budgets, heartbeat tracking) plus a new market-hours gate that refuses a job on a closed session regardless of what the freshness check alone would allow, and concrete macro(12h)/equity(1h)/chaos(1-5min) clock definitions. The specific acceptance case (a monthly source's observed date staying fixed across 60 hourly refreshes while its derived z-score still recomputes) is directly tested. **Not done**: this is not wired to an actual live cron/queue running the real engines — there is no scheduler infrastructure running anywhere outside these tests. |
| IMP-08 | **Blocked** | Needs a real market-data vendor to build a 300+ name universe with survivorship-correct history. No vendor is connected in this environment (no API keys, no network egress to a paid data provider). The *mechanism* was built one level down in DATA-02 against a 15-name synthetic sample, with a passing survivorship test — the pattern is proven, the real data is not available. |
| IMP-09 | **Done** (mechanism) | `regime-vector.ts`: fixed-order, versioned export with a staleness field and a loud compatibility assertion on any definition change. **Not yet wired** into `src/lib/state.ts`'s actual WW-STATE output — a small, safe follow-up left for a future pass since `state.ts` wasn't in this pass's file-ownership set. |
| IMP-10 | **Blocked** | Needs a real, licensed news feed with first-publication timestamps. No news vendor is connected. |
| IMP-11 | **Blocked** | Needs a real corpus-embedding pipeline and a rolling news corpus. No such feed exists in this environment. |
| IMP-12 | **Blocked** | Needs real short-interest/borrow/ownership data (slow block) and real intraday volume/quote data (fast block). No vendor connected. |
| IMP-13 | **Blocked** | Depends on a pairs/relative-value model (RES-07) that does not exist anywhere in this codebase yet — WW-GRAPH (the candidate generator this ticket wants pairs to consume) is built and tested, but building the pairs model itself was out of this list's explicit build order and out of scope for this pass. |
| IMP-14 | **Blocked** | This ticket is a documentation/definition gate ("settle what the VIXEQ-minus-VIX construct means... nothing enters a feature set until it has passed the same documentation gate") that depends on a real options/VIX data feed to even define the series against. No feed connected; nothing was fabricated in its place. |
| IMP-15 | **Done** | `src/lib/models/conviction.ts`: explicit reserved slots for the weekly forecast, graph residual, and cascade exposure, each with its own confidence; a proven, documented per-slot delta cap so no single model's removal can move the composite by more than a bounded amount; cross-references `horizons.ts` rather than duplicating its horizon logic. **Named gap**: the three slot ids are reserved placeholders — none of WW-WEEKLY/WW-GRAPH/WW-CASCADE is registered in `registry.ts` as a live website model yet, so this composite has no real model feeding it today. Searched the repo for "STS-02" (the calibration test this ticket says must still pass) — it does not exist anywhere in this codebase, so that clause has nothing to verify against. |
| IMP-16 | **Done** | `classifyDisagreement()` in `disagreement.ts` (additive — the original `computeDisagreement` export is untouched) separates directional disagreement (opposite-signed, confidence-weighted) from confidence disagreement (spread in strength among same-signed calls), with the review flag firing only on the directional kind at high conviction, exactly per spec. `DisagreementPanel.tsx` shows both separately. Driven by labeled sample data — see gap below. |
| IMP-17 | **Done** | `quant-infra/sizing/`: allocator budget vs. portfolio-risk ceiling, smaller always wins, a budget of zero forces zero regardless of the risk ceiling, and an append-only ledger recording which constraint bound on every decision. |
| IMP-18 | **Done** | `quant-infra/cost/`: square-root impact cost model, calibration from realized fills with an honest "uncalibrated" flag and a conservative default below a minimum sample size, a closed-form capacity estimate (the size where cost eats the edge), and a weekly realized-vs-predicted error tracker. |
| IMP-19 | **Done** | `quant-infra/decision/`: `DecisionOutput` deliberately carries no sizing fields (the boundary is enforced in the type shape, not just a comment); `fixed_weight_fallback` is the v1.0 shrinkage path; `get_strategy_weights` tries the real allocator solver and falls back to fixed weights with an alarm on any failure or instability — proven against the actual `quant-infra/alloc/solve.py` in an integration test. |
| IMP-20 | **Done** | `horizons.ts`: a per-model horizon registry; `assertCombinable`/`canCombine` reject an undocumented cross-horizon blend as a hard interface error. |
| IMP-21 | **Done** | `disagreement.ts`: confidence-weighted disagreement scalar feeding a review flag above a documented threshold. |

---

## Part 2 — New builds

### 1. Data layer
| ID | Status | Notes |
|---|---|---|
| DATA-01 | **Partial** | `data-router/` (117 tests): the provider-router skeleton, quota manager, circuit breaker, fallback chain, and adapter interfaces for Alpha Vantage / Tiingo / OpenBB / a local-file fixture adapter all exist and are tested against fixture data. **Not done**: no live vendor call has ever actually been made — there are no API keys and no network egress to a paid data vendor in this environment, so the adapters are proven against recorded fixtures only, never against a live endpoint. |
| DATA-02 | **Done** | `data-router/router/universe_publish/`: a 15-name synthetic universe with entry/exit dates (three intentionally-delisted names), a stored NYSE trading calendar (holidays/half-days, not computed at runtime), and a dated-JSON publisher. The literal acceptance test — a past-date query that must still include a since-delisted name — passes. Scaled down from 300+ real names per IMP-08's blocker above. |
| DATA-03 | **Blocked** | OpenBB is a third-party Python package requiring `pip install` from a real package index; there is no network access to install anything in this sandbox. An adapter stub exists in `data-router/router/adapters/openbb.py` but has never been exercised against the real package. |

### 2. Feature store and label engine
| ID | Status | Notes |
|---|---|---|
| FEAT-01 | **Done** | `feature-store/`: named feature registry refusing registration without a written rationale, a batch panel builder, a live-serving path proven identical to the batch path on the same timestamp (the ticket's own literal "done when" test), three missing-data policies (never zero-fill), cross-sectional transforms registered as their own named features, and manifest hashing. |
| FEAT-02 | **Done** | `label-engine/`: forward-return labels carrying an explicit knowable-from timestamp, vol-scaled triple-barrier labeling, sample-uniqueness weighting for overlapping windows (hand-verified against computed expected values), meta-label row construction that excludes non-firing rows entirely, and a look-ahead assertion with no disable flag of any kind. |

### 3–13. The engines (WW-WEEKLY, WW-CHAOS, WW-GRAPH, WW-CASCADE, WW-STATE, WW-ALLOC, the self-improvement loop, orchestration, the visual layer, Vibe Trading, ML validation)
| ID | Status | Notes |
|---|---|---|
| WKLY-01 | **Done** | `weekly-engine/` (48 tests): full lagged-return/RSI/momentum feature set, ridge baseline + constrained GBT + quantile heads, purged walk-forward with embargo, sector-neutralized output. |
| CHAOS-01 | **Done** | `chaos-engine/` state engine: all 8 chaos components independently registered, hysteresis state machine with minimum dwell time. |
| CHAOS-02 | **Done** | Causal dilated-convolution directional model, isotonic calibration, meta-label abstention gate. |
| CHAOS-03 | **Done** | Cost-aware execution assumptions: far-side-of-spread fills, spread widening by chaos state, gross/net side by side, cost-sensitivity table at 1x/2x/3x. |
| GRAPH-01 | **Done** | `graph-engine/` (71 tests): multi-source edges (correlation w/ Ledoit-Wolf shrinkage, sector prior, ETF co-membership), sparsified graph Laplacian diffusion, residual z-score with a fitted half-life. |
| CASC-01 | **Done** | `quant-infra/cascade/`: holdings-weighted pressure, empirically-estimated transmission coefficient, permanent/temporary decomposition. |
| STATE-01 | **Done** | `engine/incepta/state.py`: the 7-element state vector, own-history standardization, plain-language renderer (reused directly by IMP-05's dashboard panel). |
| ALLOC-01 | **Done** | `quant-infra/alloc/solve.py` (28 tests): shrunk edge estimate, uncertainty from quantile width + disagreement, cost from the execution model at actual size, shrunk covariance, convex solve with turnover penalty, hard caps/floor/shadow-mode-zero-budget, solver-failure fallback logging. |
| LOOP-01 | **Done** | Champion/challenger retraining comparison on a fixed held-out protocol; ties keep the champion. |
| LOOP-02 | **Done** | Calibration refit, feature/prediction/performance drift monitoring, automatic demotion by severity (never automatic promotion). |
| LOOP-03 | **Done** | Bounded (≤5%) exploration budget via an upper-confidence allocation rule, hard-capped regardless of performance. |
| LOOP-04 | **Blocked** | JT's Fable code file was never uploaded or provided anywhere in this conversation or the provided zip — there is nothing to review, classify, or wire. This cannot be built around; it needs the actual file from the user. |
| ORCH-01 | **Done** | Generic dependency-graph scheduler (32 tests) plus the market-hours-aware three-clock wiring described under IMP-07 above (30 more tests). |
| VIS-01 | **Done** | Chaos ribbon, dislocation field (wired to real WW-GRAPH data), cascade network, allocator ribbon; static-first, then a replay scrubber over stored sessions, both built before any live-stream claim; every view has a reduced-motion-safe static form. |
| VIBE-01 | **Blocked** | Requires installing the third-party HKUDS Vibe Trading package from its official repository, which needs network/`pip` access this sandbox does not have, and running it in an isolated container, which also does not exist here. Nothing was fabricated in its place; no factor-benchmark report can honestly be produced without the real package. |
| MLVAL-01 | **Done** | `engine/incepta/validation/splits.py`: time-only purged splits with embargo, combinatorial variant. |
| MLVAL-02 | **Done** | `trial_log.py`/`store.py`: append-only trial logging, refuses to report a raw Sharpe without its deflated counterpart. |
| MLVAL-03 | **Done** | `calibration.py` (new this pass): reliability curve + expected calibration error, the Murphy Brier decomposition (verified as an exact identity against `metrics.brier_score` on constant-per-bin synthetic forecasts), and an abstention-gate report with an explicit, documented trip condition for "the abstained subset would have been profitable." Proven to compose correctly with the existing `graduation.py` gate. |
| MLVAL-04 | **Done** | `graduation.py`: all five graduation gates (shadow length, live-vs-validation consistency, shadow calibration, model card, two-person approval) required before any non-zero budget, enforced by test. |
| WATCH-01 | **Done** | `/watch` + `src/lib/watch/checks.ts`: the full invalidation/distance/forecast-change/graph-residual/cascade/chaos/news/positioning/allocator/correlation check list. |
| WATCH-02 | **Done** | `src/lib/watch/urgency.ts`: a defined urgency scalar and plain-language band from the WW-WEEKLY quantile band and distance-to-invalidation, with a stated driving input and a scored history. **Not fed** by WW-PATH's first-passage probabilities (see PATH-07 below) — it currently uses the quantile band alone, which the doc calls a legitimate but weaker input than the touch probability. |
| WATCH-03 | **Done** (mechanism) | `src/lib/watch/slack.ts`: severity routing, one-thread-per-position, dedup/rate-limiting, quiet hours, daily/weekly digest builders — all genuinely functional string/logic layers. **Genuinely blocked** at the literal network call: there is no real Slack workspace or webhook credential connected anywhere in this environment, so no alert has ever actually been posted to Slack. The seam where a real `SlackWebhookNotifier` would plug in is explicit and documented. |

### 16. WW-PATH
| ID | Status | Notes |
|---|---|---|
| PATH-01 | **Partial / Blocked** | Surface representation (forward-moneyness/total-variance), no-arbitrage checks (calendar + butterfly via the Durrleman condition), and a synthetic SVI generator are built and tested. **Blocked**: fitting a surface from a real, live options chain needs an options-data vendor; none is connected, so this only ever runs against a synthetic or user-supplied grid, never a real chain. |
| PATH-02 | **Done** | GBM (closed-form-checked), Dupire local volatility (differentiated consistently with the pricing interpolant — a real bug in naive finite-difference bumping was found and fixed during an earlier pass), Heston under Andersen's QE discretization. |
| PATH-03 | **Done** | Full payoff library: Asian (arithmetic + geometric), all 8 barrier types, lookback, cliquet, autocallable, American/Bermudan via Longstaff-Schwartz, and first-passage/touch probability as its own payoff. |
| PATH-04 | **Done** | Antithetic variates, control variates (geometric-Asian closed form controlling the arithmetic one), Sobol sequences with Brownian bridge construction, discrete-barrier bridge correction, common random numbers, standard error on every price, an enforced convergence test. |
| PATH-05 | **Not built** | Greeks/sensitivities (bumping with common random numbers, pathwise/likelihood-ratio for discontinuous payoffs) were never implemented — no `greeks.py`-equivalent module exists anywhere in `path-engine/`. This was explicitly marked P2 ("genuinely optional until there is an instrument in front of us") in the source doc, and time this pass went to the P0/P1 items above it instead; it is a real, honest gap, not a disguised one. |
| PATH-06 | **Done** | Closed-form checks (European vs. Black-Scholes, geometric Asian, continuous barrier), put-call parity, calibration-set repricing, and a published three-model (local-vol/Heston/bootstrap) comparison as the standing model-risk measure. |
| PATH-07 | **Not built** | The payoff functions this wiring needs (`touch.py`'s first-passage/touch probability) exist and are tested in isolation, but the actual cross-module wiring — feeding touch probabilities into WW-WATCH's urgency score, simulated portfolio-outcome distributions into RISK-01, or touch-probability-based barriers into FEAT-02's labels — was never built. This is an honest, explicitly-flagged gap: the pieces exist, the wiring does not. |

---

## Everything genuinely blocked, in one place, with the specific missing dependency

- **A real market-data vendor** (Alpha Vantage / OpenBB / any paid feed) — blocks IMP-08, IMP-10 through IMP-14 (mostly), PATH-01's live chain, DATA-03, and keeps DATA-01/universe work at sample scale.
- **Network / `pip install` access** — blocks DATA-03 (OpenBB) and VIBE-01 (the third-party Vibe Trading package) outright.
- **Real per-user authentication** (Clerk / Auth.js / Supabase Auth credentials) — blocks wiring IMP-03's already-built authorization model into any actual page or route.
- **A real Slack workspace/webhook** — blocks WATCH-03's already-built alert logic from ever posting a real message.
- **JT's Fable code file** — was never provided in this conversation or the uploaded zip. LOOP-04 cannot proceed at all without it.
- **A live cron/queue/scheduler runtime** — the ORCH-01 scheduler and its three clocks are real and tested, but nothing in this environment actually runs them on a timer against production engines.

None of these were worked around with fabricated data, a fake vendor response, or an invented file. Every blocked item above has real, tested infrastructure built up to the exact point where a real external credential or file would be needed, and stops there honestly.

## Added mid-engagement: design consistency and interlinking (user request)

After reviewing the team's live deployed site (whitewater-management.vercel.app/dashboard — an older deployment than this repo, used here purely as the design reference), the user asked that every model/engine be presented in that same visual system and be easy to find from one another. **Done**: a dedicated audit pass reviewed all 17 pages/components built or touched this engagement against the site's real design tokens (`src/app/globals.css`) and shared components (`src/components/ui.tsx`'s `Card`/`Stat`/`Badge`, `ModuleNav`) — everything was already consistent except one file (`MacroReader.tsx` had a duplicate local copy of `Card` instead of importing it; fixed to import the real one). The audit also found WW-WEEKLY was the one real engine with no page of its own — its ranked cross-section was only ever read internally by WATCH-02 — so a new `/weekly` page was built in the same design system, reading the real `getWeeklyExport()` data with the same honest "not synced" fallback every other real-data reader uses, and added to the dashboard's module launcher. The `/models` registry page gained a new "Sealed backend engines" section listing WW-STATE, WW-ALLOC, WW-GRAPH, WW-CHAOS, WW-CASCADE and WW-WEEKLY with a link to wherever each is actually surfaced, so every real piece of the system is discoverable from one hub. Round-trip navigation (dashboard → any page → back to dashboard via `ModuleNav`) was confirmed for every page.

## Added mid-engagement: WHITEWATCH / War Map integration (user-supplied package)

The user uploaded a separate package (`whitewaterintegration_1.zip`) — a "War Map" geopolitical conflict-monitoring feature (WHITEWATCH), built by a different tool/session entirely, not part of any Notion checklist item. It was **not previously in this repo at all** before this pass. It has now been integrated:

- **What it is**: a new `/war-map` page — a self-contained "trading terminal" style dashboard (MapLibre GL globe with country threat-tier shading, an Intel Feed of live RSS + GDELT headlines, a World Bank/IMF/UNHCR indicators tab, a Predictions tab, a Daily Report, and a status Dashboard tab) backed by 12 new Next.js Route Handlers under `/api/whitewatch/*`. No new Python engine, no new database — it's an external-data integration, not a pricing model.
- **Mechanical move performed**: this repo uses a `src/` layout and the package was authored for a root `app/`/`lib/` layout, so `app/war-map/` → `src/app/war-map/`, `app/api/whitewatch/` → `src/app/api/whitewatch/`, and `lib/whitewatch-data/` → `src/lib/whitewatch-data/` (its two curated JSON fixtures). Because both sides of every relative import moved under `src/` together, no import path needed to change — verified by bundling every one of the 12 route files and both `war-map` files with esbuild (mirroring the package's own stated verification method) and confirming every import resolves with zero errors, and by validating both JSON fixtures parse.
- **Dependencies added** to `package.json`: `maplibre-gl`, `topojson-client`, `world-atlas`, `rss-parser`. These are pinned to `"latest"` rather than a guessed version number, since this sandbox has no network access to check what the real current published versions are — `latest` will resolve correctly the first time `npm install` actually runs somewhere with network access, rather than risking a hand-typed version that doesn't exist.
- **Environment variables**: `.env.local.example` (blank template, documents 8 optional keys) and `.env.local` (the user's real, already-supplied `FIRMS_MAP_KEY` and `FRED_API_KEY` — the package's only two live keys; everything else, including the paid X/Twitter tier and the optional Anthropic key for live predictions, is left unset and degrades to an explicit "not connected" placeholder rather than breaking) were placed at the repo root. `.gitignore`'s existing blanket `.env*` rule was given one narrow exception (`!.env.local.example`) so the safe template commits but the real key file never does — confirmed both ways with `git check-ignore`.
- **Interlinking**: added a `WHITEWATCH` entry to the dashboard's module launcher (linking to `/war-map`, labeled as external context rather than a model), and added a small "← Whitewater" link into the War Map's own top bar (it previously had no way back to the rest of the site at all) using the same accent color already defined in its self-contained stylesheet.
- **Design**: left the page's existing self-contained dark "trading terminal" visual style as-is rather than rebuilding it in the main site's `Card`/`ModuleNav` component system. It's a large (1,285-line), already-cohesive, un-compiled JSX file with its own inline stylesheet; with no TypeScript/JSX compiler available in this sandbox to safely verify a deeper rewrite, a full visual reconciliation risked introducing a real bug for a cosmetic gain. The one addition (the back-link) reuses the file's own existing CSS variables so it matches its palette exactly.
- **Verification status carried forward honestly**: the package's own README states it plainly — "written but not build-tested." Nothing in this pass changes that: no `next build`, `npm install`, or browser run has ever been performed on this feature, here or in the environment it was built in. What has been verified, both by the original package's author and independently here: every JS/JSON file parses correctly, every import path resolves to a real file, and (per the package's own README) the real external APIs it calls were fetched for real during its own development to confirm response shapes. It should be treated exactly like every other piece of this repo that has real logic but no compiler-verified build — sanity-check `/war-map` in a real `npm run dev` before relying on it.

## Recommended next steps, in priority order

1. Provide JT's Fable file (LOOP-04) — this is pure waiting on the user, not a technical blocker.
2. Pick and connect a real market-data vendor (Alpha Vantage premium tier, or OpenBB with its per-provider keys) — this alone unblocks IMP-08's universe widening, most of IMP-10 through IMP-14, and DATA-03.
3. Stand up real per-member authentication (Clerk is the fastest path) to activate the IMP-03 authorization model that's already built and tested.
4. Connect a Slack workspace/webhook to activate WATCH-03's already-built alerting.
5. Run `npm install` somewhere with network access and a real `next build` — this is the one verification this whole engagement could not perform, and it should be done before this codebase is treated as production-ready.
6. Wire IMP-09's regime vector into `state.ts`, and PATH-07's touch probabilities into `watch/urgency.ts` — both are small, well-scoped follow-ups against infrastructure that already exists and is already tested.
7. For WHITEWATCH: add `FIRMS_MAP_KEY` and `FRED_API_KEY` (already known, real values — see `.env.local`) to Vercel's Environment Variables so the deployed site picks up live fires/commodities data, not just local dev. Optionally add `ANTHROPIC_API_KEY` (free) for live Predictions, and decide whether the paid X Developer Basic tier is worth it for the X panel.
