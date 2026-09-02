# Equity Research & Trade-Stress-Testing System — Research Dossier

**Mode:** Research-only. No application code. Primary sources prioritized. Claims that could not be verified against a primary/current source are marked **UNVERIFIED**.
**Prepared for:** the system architect who will turn this into a quantitative spec, architecture, and coding-agent instructions.
**As-of date:** 2026-08-04. All data-source terms were checked against sources dated 2025–2026 where possible; **data-provider terms change frequently — re-verify each provider's pricing/limits/licence page at build time.**

**Confidence scale used throughout:** High = replicated academic evidence or primary/official documentation; Medium = strong single-study evidence or standard industry practice; Low = plausible inference / contested. Evidence tags: [Academic], [Industry practice], [Inference], [Official docs].

---

## 1. Executive Summary

**The core design decision.** The system you described is not one model. It is a *pipeline of separable analyses* — descriptive, risk, valuation, forecasting, stress, sizing — bound together by a data-quality/confidence layer and an explanation layer. The single most important architectural instruction in this dossier is: **do not collapse these into one opaque score.** Each layer must emit its own output, its own uncertainty, and its own data-provenance so that the explanation layer can show *why*, and so the model-risk layer can veto low-confidence conclusions. This is both an econometric requirement (the layers have different statistical difficulty and different failure modes) and a governance requirement.

**What is realistically achievable on free/low-cost data (High confidence).** With SEC EDGAR (fundamentals, filings, insider Form 4, 13F), FRED (rates/macro controls), the Ken French Data Library (factor returns), FINRA (short interest), and one price/corporate-action vendor, a small team can build a defensible **cross-sectional, daily-to-multi-month equity model** that does: factor-exposure estimation, valuation vs. history/peers, quality/distress scoring, momentum/technical state, event-risk flags, volatility/liquidity/tail estimation, historical + Monte Carlo stress testing, and risk-based position sizing. This is genuinely useful and defensible.

**What is *not* realistically achievable on free data (High confidence).**
- **Intraday prediction.** Free feeds are end-of-day or 15-minute delayed (Polygon/Massive free, Alpha Vantage). Intraday alpha requires paid tick/L1-L2 data, microstructure infrastructure, and colocation-grade latency. **Recommend excluding intraday from v1 entirely** and saying so explicitly to users.
- **Point-in-time fundamentals for free.** SEC XBRL gives you filing dates (so you *can* build PIT correctly by hand), but pre-built, cleaned, survivorship-free, restatement-aware PIT fundamental panels are a paid product (Sharadar, Compustat PIT). Free fundamentals require you to *construct* PIT integrity yourself, carefully.
- **Reliable delisted-security / survivorship-free history for free.** This is the classic hole in free data and the fastest route to a fake backtest.
- **Options-implied data at scale for free.** VIX and index-level data are free; per-name option chains and historical implied-vol surfaces are effectively paid.

**The honest expectation to set with your four partners.** Published equity anomalies decay substantially after publication — McLean & Pontiff (2016) estimate return predictability falls ~26% out-of-sample and ~58% post-publication [Academic, High]. The realistic deliverable is a **risk-and-evidence engine that improves decision quality and prevents blow-ups**, not a return-prediction machine that "beats the market." Frame the product around *risk, assumptions, and disconfirmation* — where the math is strong — not around return forecasting, where it is weak.

**The two biggest technical dangers**, which the architecture must be built to prevent structurally (not by discipline alone): **(1) look-ahead / point-in-time leakage** in fundamentals and index membership, and **(2) multiple-testing / backtest overfitting** from searching many signals. Both are addressed with dedicated sections and enforced defaults below.

---

## 2. Recommended Scope for the First Equity-Model Version (v1 / MVP)

**In scope for v1 (High confidence these are buildable and defensible on free data):**
1. **Universe:** US-listed common stocks above a liquidity/market-cap floor (e.g. > $300M cap, > $2M median daily $ volume — tune later), plus a handful of ETFs strictly as *benchmarks/factor proxies* (SPY/IVV, sector SPDRs, IWM, MTUM/QUAL/VLUE/USMV as factor references).
2. **Horizons:** 1–5 day, several-week swing, and 3–12 month. **Not intraday. Not multi-year fundamental compounding** (data depth and regime issues make the very-long horizon hard to validate).
3. **Layers (see §4):** identifier resolution → market-data validation → corporate-action adjustment → fundamental processing → feature engineering → factor exposures → valuation → quality/health → momentum/technical → event risk → volatility/liquidity/tail → cross-sectional ranking (baseline) → scenario/stress engine → position sizing → confidence/data-quality → explanation/adversarial-thesis.
4. **Primary quantitative outputs:** (a) cross-sectional percentile rank of expected relative return within sector/universe; (b) factor-exposure decomposition; (c) valuation-vs-history/peers; (d) distress & earnings-quality flags; (e) volatility/liquidity/tail estimates; (f) stress-test P&L distribution for the *specific proposed trade*; (g) risk-based max position size; (h) an explicit **assumption/disconfirmation list**; (i) a **confidence score** driven by data quality and out-of-distribution checks.
5. **Prediction target for the baseline model:** *cross-sectional rank of horizon-ahead sector-neutral excess return* (see §4 for why ranking beats price prediction).

**Explicitly out of scope for v1:** intraday signals; per-name options-implied features; live borrow-cost feeds; neural nets/transformers; portfolio optimization beyond simple risk budgeting; anything requiring real-time data.

**Second phase:** probability-of-hitting-target-before-stop (first-passage/barrier) model; earnings-surprise-direction model; GARCH-family conditional vol; richer factor risk model with shrinkage; champion/challenger infrastructure; paid PIT fundamentals (Sharadar) if the product proves out.

**Advanced phase:** gradient-boosted ranking with rigorous purged CV + deflated Sharpe gating; options-implied features (paid); regime-conditional models; NLP on filings/calls as *features* (not as the engine).

---

## 3. Questions the System Can and Cannot Answer

### Can answer well (math is strong, data available) — High/Medium confidence
| Question | Basis | Confidence |
|---|---|---|
| Is this trade unusually risky vs. peers/its own history? | Realized/downside vol, beta, spread/liquidity, gap history | High |
| What factors drive its return? | Rolling factor regressions on Ken French / ETF proxies | High |
| Is it expensive vs. its own history, sector, peers? | Valuation z-scores vs. trailing distribution & peer set | High |
| What balance-sheet / distress / dilution / earnings-quality risks exist? | Altman/Ohlson/Campbell distress, Sloan accruals, Beneish, share-count deltas from XBRL | High |
| How sensitive is it to market/sector/rates/commodity/FX moves? | Factor betas + scenario shocks | Medium–High |
| How might it perform under historical & hypothetical shocks? | Historical scenario replay + factor-shock + Monte Carlo | Medium–High |
| How large could a drawdown / overnight gap loss be? | Historical gap distribution, ES/CVaR, jump modeling | Medium |
| Is the proposed size appropriate for the risk? | Vol targeting, stop-based sizing, ES constraint, fractional Kelly | High |
| Which assumptions must hold for the thesis? | Reverse-DCF implied expectations + factor/scenario dependencies | Medium |
| What new info should trigger review/close? | Event calendar, revision/short-interest/insider deltas, drift monitors | Medium |

### Can answer only weakly / with heavy caveats — Low/Medium confidence
- **"Will this stock go up next week/month?"** — Directional single-name forecasting is low-signal; express as *probabilistic, cross-sectional, sector-neutral* rank, never a point price. [Academic, High that this is hard]
- **"Is the evidence strong enough to justify the trade?"** — The system can quantify *statistical* strength (IC, calibration, confidence) but cannot certify a thesis. Must be framed as evidence-weighing, not a verdict.

### Cannot answer / must refuse — High confidence
- **Intraday timing** on free data.
- **Personalized investment advice / "should I buy this"** — the product must present evidence and risk, not a recommendation to a specific person's circumstances (also a compliance line; the *user* decides).
- **Guaranteed or expected profit** — never output a profit promise.
- Anything where data is stale, missing, contradictory, or out-of-distribution → the confidence layer must force **abstention**.

**Design rule:** every answer is tagged as **descriptive / risk-estimate / forecast / valuation / stress / thesis-evaluation / sizing**, and never merged into one number without the components remaining inspectable.

---

## 4. Recommended Model Layers

Your proposed 18-layer structure is sound. Recommended refinements (High confidence on structure; the ordering matters for leakage control):

1. **Security & identifier resolution** — ticker ↔ CIK ↔ FIGI ↔ (CUSIP/ISIN where licensed). Handle ticker reuse/changes over time (this is a *survivorship/PIT* issue, not cosmetic). Source: OpenFIGI + SEC CIK map.
2. **Market-data validation** — sanity checks (spikes, zero-volume, stale prints, splits not applied), cross-source reconciliation.
3. **Corporate-action adjustment** — splits, dividends, spin-offs; keep *both* adjusted and unadjusted series; store action dates.
4. **Fundamental-data processing** — XBRL normalization, standardization across taxonomies, unit/scale handling, restatement tracking.
5. **Point-in-time assembly** *(elevate this to its own first-class layer — your list embedded it implicitly)* — stamp every datum with fiscal-period-end, filing date, public-release timestamp; expose data only as-of the decision time. **This is the layer that prevents the most dangerous bug in the system.**
6. **Feature engineering** — all features computed from the PIT view only.
7. **Factor-exposure estimation** — rolling/shrunk regressions vs. factor set.
8. **Valuation analysis** — multiples, yields, reverse-DCF, scenario-DCF, peer/history z-scores.
9. **Quality & financial-health** — profitability, accruals, leverage/coverage, distress scores.
10. **Momentum & technical-state** — multi-horizon momentum, reversal, trend, 52-wk high.
11. **Earnings & event-risk** — earnings calendar, surprise/revision history, PEAD state, filing-change flags.
12. **Sentiment & positioning** — short interest, insider trades, 13F concentration, (later) options/news.
13. **Return/ranking model** — cross-sectional rank (baseline).
14. **Volatility, liquidity & tail-risk model** — realized/downside vol, EWMA→GARCH, spread/impact, gap/jump, ES.
15. **Scenario & stress engine** — historical replay, hypothetical factor shocks, statistical simulation; long/short-specific.
16. **Position-sizing & portfolio-impact** — risk-based sizing + portfolio marginal risk/overlap.
17. **Confidence & data-quality layer** — data completeness, staleness, out-of-distribution, multiple-testing awareness → gate/abstain.
18. **Explanation & adversarial-thesis (LLM here, and only here)** — narrate, steelman the *bear* case, list disconfirming evidence, summarize filings. Never feeds back into the numeric engine.

**Recommended additions:** an explicit **event/corporate-action calendar service** feeding layers 11 & 15; and a **provenance/lineage store** (every output traces to inputs + as-of timestamps) feeding layers 17 & 18 and the audit log (§14).

---

## 5. Equity-Signal Evidence Table

Legend: **Decay** = known post-publication weakening (McLean & Pontiff 2016 [Academic, High]). **After costs?** = survives realistic trading costs at small scale.

### Fundamental
| Signal | Core evidence | Direction | Horizon | After costs? | Confidence | Reliability caveats |
|---|---|---|---|---|---|---|
| Gross profitability | Novy-Marx (2013, JFE) | + | Months–yr | Often | High | Weakens for financials/REITs |
| Profitability/Investment (RMW/CMA) | Fama-French (2015, JFE) | +/− | Months–yr | Some | High | Definitions matter |
| Accruals (earnings quality) | Sloan (1996, TAR) | Low accruals + | Qtrs | Decayed but present | High | Decays post-pub; sector-sensitive |
| Piotroski F-score | Piotroski (2000, JAR) | High + | Months | In value/small caps | High | Strongest in cheap/small names |
| ROIC/ROE/ROA | Quality literature; QMJ (Asness-Frazzini-Pedersen 2019, RoF) | + | Months–yr | Some | High | ROE distorted by leverage/buybacks |
| Leverage & interest coverage | Distress literature | Context | Months | Risk flag, not alpha | Medium | Bank/insurer leverage not comparable |
| Net share issuance / dilution | Pontiff-Woodgate (2008, JF); Daniel-Titman | Issuance − | Months–yr | Yes (robust) | High | Very robust; watch SBC-heavy names |
| Buybacks | Ikenberry et al; mixed | + weak | Months–yr | Marginal | Medium | Financing vs. value distinction |
| Insider transactions | Lakonishok-Lee (2001); Cohen-Malloy-Pomorski (2012) | Buys + | Weeks–months | "Routine vs opportunistic" matters | Medium | Noisy; cluster/opportunistic filter needed |
| Institutional ownership / 13F | Mixed; crowding risk | Context | Qtr (45-day lag!) | Not alpha alone | Low–Medium | 13F is ≥45 days stale; longs only |
| Distress: Altman Z (1968), Ohlson O (1980), Campbell-Hilscher-Szilagyi (2008, JF) | Distress risk | High distress − | Months | Risk flag | High | CHS best modern; Z-score dated for non-manufacturers |
| Beneish M-score (1999, FAJ) | Manipulation flag | Flag | — | Screening | Medium | Screening tool, not alpha |
| FCF generation / FCF yield | Value/quality | + | Months–yr | Some | Medium | Capex cyclicality |

### Valuation
| Signal | Evidence | Reliability breaks down for… | Confidence |
|---|---|---|---|
| E/P (earnings yield), B/M (value) | Fama-French (1992/1993); Basu (1977) | Negative-earnings, asset-light, high-growth | High (factor exists), Medium (decayed) |
| EV/EBITDA, EV/Sales | Loughran-Wellman (2011) EV/multiples | Banks/insurers (no EV), negative EBITDA | Medium |
| P/B | FF value | **Banks OK; tech/IP-heavy misleading** (intangibles) | High/Medium |
| FCF yield | Value/quality | Capex-heavy cyclicals, early-stage | Medium |
| Dividend yield | Weak standalone; value proxy | Non-payers; yield traps | Low–Medium |
| PEG / growth-adjusted | Practitioner; weak academic support | Fragile growth estimates | Low |
| Reverse-DCF (implied expectations) | Practitioner (Mauboussin) | Requires WACC/terminal assumptions | Medium (as *framing* tool) |
| Scenario DCF | Standard valuation | Garbage-in for unstable businesses | Medium |
| Historical & peer-relative z-scores | Standard practice | Regime shifts change "normal" | Medium–High |

**Sector-specific unreliability (High confidence):** **Banks/insurers** — use P/B, P/TBV, ROTCE, not EV/EBITDA or FCF. **REITs** — use P/FFO, P/AFFO, NAV, not P/E. **Early-stage/negative-earnings** — use EV/Sales, growth durability, cash runway; P/E meaningless. **Commodity producers** — normalize through the cycle (mid-cycle margins), P/E is pro-cyclically misleading. **Asset-light/IP-heavy** — P/B distorted by unrecognized intangibles.

### Market / Technical
| Signal | Evidence | Horizon | Confidence | Notes |
|---|---|---|---|---|
| Cross-sectional momentum (2–12m, skip most recent month) | Jegadeesh-Titman (1993, JF); Asness-Moskowitz-Pedersen (2013) | 1–12m | High | **Momentum crashes** in rebounds — Daniel-Moskowitz (2016, JFE); needs vol-scaling |
| Short-term reversal (1 week–1 month) | Jegadeesh (1990); Lehmann (1990) | Days–weeks | High | Alpha largely eaten by costs at small scale |
| 52-week-high proximity | George-Hwang (2004, JF) | Months | Medium | Momentum cousin |
| Realized vol / downside vol | Standard | All | High | Downside (semi-)deviation for asymmetric risk |
| Low-vol / low-beta anomaly | Ang-Hodrick-Xing-Zhang (2006, JF); Frazzini-Pedersen BAB (2014, JFE) | Months | High | BAB robust; leverage-constraint story |
| Beta / downside beta | Standard; Ang et al downside beta | All | High | Estimate with shrinkage |
| Volume / turnover / Amihud illiquidity | Amihud (2002, JFM) | Months | High | Illiquidity premium ↔ capacity limit |
| Bid-ask spread estimates | Corwin-Schultz (2012, JF) high-low estimator | All | High | **Lets you estimate spread from OHLC without quote data** |
| Abnormal volume | Event-study literature | Days | Medium | Confirmation signal |
| Overnight vs intraday returns | Lou-Polk-Skouras (2019, JFE) | Days | Medium | Overnight/intraday drift documented |
| Support/resistance, chart patterns | Weak/contested academic support | — | Low | Include only as descriptive context, not signal |

### Estimate / Event
| Signal | Evidence | Confidence | Notes |
|---|---|---|---|
| Post-earnings-announcement drift (PEAD) | Ball-Brown (1968); Bernard-Thomas (1989/90) | High | One of the most robust anomalies; decayed but alive |
| Earnings/revenue surprise (SUE) | Foster-Olsen-Shevlin (1984) | High | Drives PEAD |
| Analyst revisions momentum | Chan-Jegadeesh-Lakonishok (1996, JF); Womack | High | Revisions predict drift |
| Guidance changes | Practitioner + event studies | Medium | Data access harder for free |
| Earnings-call language (NLP) | Loughran-McDonald (2011, JF) finance dictionaries | Medium | Feature only; LM lexicon is free |
| Filing textual change / similarity | Cohen-Malloy-Nguyen (2020, JF) "Lazy Prices" | Medium | 10-K/Q change predicts returns — computable from EDGAR |
| Short interest / days-to-cover | Asquith-Pathak-Ritter (2005); Boehmer-Jones-Zhang (2008) | High | High SI predicts underperformance; squeeze risk on shorts |
| Options-implied (skew, IV, put/call) | Extensive; e.g. Xing-Zhang-Zhao (2010) | Medium | **Data effectively paid** — defer |
| Index add/delete | Shleifer (1986); effect has shrunk | Medium | Event risk both directions |

### Behavioral (separate evidence from folklore)
| Effect | Empirically supported? | Confidence | Note |
|---|---|---|---|
| Underreaction (drift) → PEAD, revisions | Yes | High | Strong |
| Overreaction / long-term reversal | De Bondt-Thaler (1985) | Medium | 3–5yr; long horizon |
| Disposition effect | Odean (1998) | High (behavior), Medium (as tradable signal) | Underlies momentum/PEAD |
| Attention (news/volume spikes) | Barber-Odean (2008); Da-Engelberg-Gao (2011, "FEARS"/Google) | Medium | Retail attention proxies |
| Herding / narrative crowding | Documented but hard to trade | Low–Medium | Crowding = risk factor, not alpha |
| Anchoring (to 52-wk high) | George-Hwang | Medium | Feeds momentum |
| Short squeeze dynamics | Real risk (2021 events) | Medium | Model as *risk*, high SI + low float + high borrow |
| "It worked in my backtest" patterns w/o mechanism | **Folklore** | — | Exclude by default |

---

## 6. Prediction-Target Comparison Table

| Target | Best horizon | Statistical difficulty | Data needed | Label construction | Leakage risk | Eval metrics | Economic meaning | Small-team suitability |
|---|---|---|---|---|---|---|---|---|
| Next-period raw return | Any | Very high (low signal, dominated by market) | Prices | Fwd return | Med | MAE, R² (tiny), Sharpe | Weak alone | Poor |
| Excess return vs benchmark | Weeks–12m | High | Prices + bmk | Fwd ret − bmk | Med | IR, IC | Better | Medium |
| **Sector-neutral excess return** | Weeks–12m | High but *relative* | Prices + GICS/sector | Fwd ret − sector mean | Med | IC, rank-IC | **Isolates stock-specific view** | **Good** |
| **Cross-sectional rank** of above | 1–12m | High but robust | Prices + universe | Percentile of fwd ret | **Low if done right** | **Rank-IC**, quantile spread | "Better than peers" | **Best for baseline** |
| P(positive excess return) | Weeks–12m | High | Prices + bmk | Binary | Med | Brier, log-loss, calibration | Confidence framing | Good |
| **P(target before stop)** (first passage) | Days–weeks | High (path-dependent) | Prices (+ intraday ideally) | Barrier hit label (triple-barrier) | **High (path leakage)** | Brier, calibration, EV | Directly answers the user's trade | Medium (v2) |
| Expected max drawdown | Trade horizon | Medium | Prices | Realized MDD over horizon | Med | Quantile loss | Risk sizing | Good |
| Expected shortfall / tail-loss prob | Trade horizon | Medium | Prices | Empirical/parametric tail | Low | Kupiec/Christoffersen backtests | **Core risk output** | **Good** |
| Volatility | Any | **Low (most predictable)** | Prices | Realized vol fwd | Low | QLIKE, MSE | Sizing, stress | **Excellent — start here** |
| Earnings-surprise direction | Around events | High | Estimates + actuals | Sign(actual−est) | High (estimate timing) | AUC, Brier | Event trades | Medium (v2) |
| Trade-failure probability | Trade horizon | High | Prices + features | Stop-hit or −X% | High (path) | Brier, calibration | Sizing/veto | Medium |
| Risk-adjusted return (Sharpe-like) | Months | High | Prices | Fwd ret/vol | Med | IR | Combines | Medium |

**Key conclusions (High confidence):**
- **Volatility is the most forecastable quantity in the list — build it first and lean on it** (it powers sizing and stress). [Academic]
- **Cross-sectional ranking is far more defensible than predicting exact prices/returns.** It cancels market-wide moves, reduces the burden from "forecast the future" to "order stocks better than random," is naturally sector-neutralizable, and uses rank-IC which is robust to outliers. **Make this the baseline target.** [Academic + Industry, High]
- **Path-dependent targets (P(target before stop), triple-barrier labels — López de Prado 2018) directly answer the user's question but carry the highest leakage risk** (overlapping labels, path information). Defer to v2 and use purging/embargo + uniqueness weighting.

---

## 7. Quantitative-Model Comparison Matrix

For each: intuition / use / assumptions / min sample / interpretability / calibration / pros / cons / failure modes / cost / overfit risk / horizon fit / phase.

| Model | Intuition | Interpret. | Min sample | Overfit risk | Calibration | Best use here | Cost | Phase |
|---|---|---|---|---|---|---|---|---|
| **Transparent scoring (z-score composites)** | Standardize & average signals | **Very high** | Low | Low | N/A (ranks) | **Baseline ranking, valuation/quality composites** | Trivial | **v1** |
| Linear regression (OLS) | Linear conditional mean | High | ~10–20×features | Medium | Good if assumptions hold | Factor exposures, simple return reg | Trivial | v1 |
| **Fama-MacBeth (1973) cross-sectional regression** | Period-by-period cross-sec regressions, average coeffs w/ robust SE | High | Many names × periods | Low–Med | N/A | **Factor premia estimation, signal testing** | Low | v1 |
| Logistic regression | Linear log-odds | High | ~10 events/feature | **Excellent w/ Platt/isotonic** | Good | P(up), P(target-before-stop), distress | Trivial | v1 |
| **Ridge / Lasso / Elastic Net** | Regularized linear; shrink/select | High (esp. Lasso) | Moderate | **Low (regularization is the point)** | Good | Many-feature return/vol models w/o overfit | Low | **v1** |
| Quantile regression | Model conditional quantiles | Med–High | Moderate | Medium | N/A | **Downside/tail estimates, drawdown quantiles** | Low | v2 |
| GAM (generalized additive) | Nonlinear but additive/interpretable | Med–High | Moderate–large | Medium | Good | Nonlinear valuation/quality relations w/ interpretability | Medium | v2 |
| Random forest | Bagged trees | Low–Med (SHAP helps) | Large | Medium | Needs calibration | Nonlinear ranking, feature screening | Medium | v2 |
| **Gradient-boosted trees (XGBoost/LightGBM), incl. LambdaMART ranking** | Boosted trees; ranking objective | Low (SHAP) | **Large (thousands+ rows)** | **High — needs purged CV + DSR gating** | Needs calibration | **Cross-sectional ranking (advanced)** | Medium | **Advanced** |
| Learning-to-rank models | Directly optimize ranking loss | Low | Large | High | N/A | Cross-sectional rank | Medium | Advanced |
| Bayesian (hierarchical/shrinkage) | Priors + uncertainty | Med–High | Flexible | Low (priors regularize) | **Native uncertainty** | **Small-sample estimates, sector pooling, confidence layer** | Medium | v2 |
| Regime-conditional (HMM/threshold) | Params switch by state | Medium | Large | **High (few regime obs)** | Hard | Conditioning stress/vol on regime | Medium | Advanced |
| Survival / hazard (Cox, discrete-time) | Time-to-event | Med–High | Many events | Medium | Good | **Distress/bankruptcy timing, time-to-stop** | Medium | v2 |
| **EWMA volatility (RiskMetrics)** | Exp-weighted variance | High | Low | **Very low** | N/A | **v1 volatility & covariance** | Trivial | **v1** |
| **GARCH family (GARCH, GJR/EGARCH)** | Vol clustering + leverage | Med | ~500+ obs | Low–Med | Good | Conditional vol, vol-of-vol for stress | Low | v2 |
| **Factor models (FF5+MOM, PCA/statistical)** | Returns = factor exposures + idio | High | Rolling window | Low–Med | N/A | **Risk decomposition, hedging, stress** | Low | **v1** |
| Ledoit-Wolf shrinkage covariance (2004) | Shrink sample cov to structured target | Med | Moderate | **Low** | N/A | **Portfolio risk when N≈T** | Low | v1/v2 |
| Monte Carlo simulation | Simulate P&L paths | Med | Depends on model | Model-dependent | N/A | **Stress, gap/jump, ES, sizing** | Medium | v1 (simple) |
| Copulas (Gaussian/t/Clayton) | Model dependence separate from margins | Low–Med | Large | High | Hard | Tail-dependence in stress (justify first) | Medium | Advanced |
| Neural nets / transformers | Flexible nonlinear/sequential | **Very low** | **Very large + stationary-ish** | **Very high** | Poor w/o work | **Not justified in v1/v2 for tabular equity data** | High | Advanced/if-earned |

**Golden rule (High confidence, echoing the assignment):** *prefer the simplest model that performs reliably out-of-sample; complexity must be earned by measurable, cost-aware, deflated out-of-sample improvement.* On tabular financial data with low signal-to-noise, gradient-boosted trees are the practical ceiling; deep learning rarely beats well-regularized linear/GBT models on cross-sectional equity tasks and is far easier to overfit. [Academic + Industry]

---

## 8. Recommended Baseline & Advanced-Model Candidates

**Baseline (v1) — deliberately transparent:**
- **Volatility:** EWMA (λ≈0.94 daily per RiskMetrics; re-estimate) → feeds sizing & stress.
- **Risk decomposition:** rolling OLS/ridge factor betas on FF5+MOM (Ken French) + sector ETF + a rates proxy (FRED 10Y / TLT) + relevant commodity/FX ETF; idiosyncratic vol as residual.
- **Ranking:** z-scored composite across value, quality, momentum, low-vol, revisions — combined with equal or inverse-vol weighting, **sector-neutralized**, validated by rank-IC. This is a defensible, explainable "smart composite," not a black box.
- **Valuation:** multiples + z-scores vs. 5–10y own history and peer set + a reverse-DCF "what's priced in" panel.
- **Distress/quality:** Piotroski F, Campbell-Hilscher-Szilagyi distress, Sloan accruals, Beneish M (flag), share-count trend.
- **Stress:** historical replay + factor-shock + simple Monte Carlo with fat tails (Student-t) and gap overlay.
- **Sizing:** vol-target + stop-based + ES cap + fractional Kelly ceiling.

**Advanced candidates (earn them):**
- GJR-GARCH conditional vol; DCC for time-varying correlations.
- LightGBM LambdaMART cross-sectional ranker, **only** if it beats the composite on purged CV *and* survives Deflated Sharpe after accounting for the number of trials.
- Discrete-time hazard model for distress/time-to-stop.
- Bayesian hierarchical shrinkage for sector-pooled estimates and native uncertainty into the confidence layer.

---

## 9. Factor & Portfolio-Risk Framework

**Recommended factor set (v1):** Market, Size (SMB), Value (HML), Momentum (WML/UMD), Profitability (RMW), Investment (CMA), Low-vol/BAB, plus **sector/industry** (GICS or SIC), a **rates** factor (Δ10Y or TLT/IEF returns from FRED), and where relevant a **commodity** (e.g. XLE/oil) and **currency/USD** (DXY/UUP) factor. Liquidity (Amihud/Pastor-Stambaugh-style) as v2. [Academic, High — these are the canonical, replicated factors; note replication debate in §17.]

**Estimation approach:**
- **Time-series factor model** (Ken French factor returns are free & daily) → per-stock exposures via **rolling regression with shrinkage** (ridge or Ledoit-Wolf on the covariance). Rolling window ~1–2y daily; report exposure *and* its standard error.
- **Cross-sectional (fundamental) factor model** (Barra-style: exposures from characteristics, factor returns estimated by cross-sectional regression each period) is the industry standard for *risk* attribution and is buildable from your own characteristic data — recommend as v2 for cleaner risk decomposition.
- **Statistical factors (PCA)** as a cross-check for missed common risk.

**Compute:**
- **Factor exposures** β via regression (shrunk).
- **Idiosyncratic risk** = residual variance; monitor because idio vol has its own anomaly (Ang et al 2006) and is where single-name blowups live.
- **Marginal risk contribution** MRC_i = w_i (Σw)_i / σ_p; **component VaR/ES** for the portfolio.
- **Expected drawdown contribution** via simulation, not closed form.
- **Correlation concentration / crowding:** eigenvalue concentration of the correlation matrix; **portfolio overlap** = active-share-style and factor-exposure overlap between the proposed trade and existing book; flag **crowded factor exposure** (e.g., the trade piles onto an already-large momentum tilt).
- **Hedged vs unhedged risk:** show residual (idiosyncratic) risk after neutralizing market/sector/factor — this is the "pure thesis" risk.

**Free-data-compatible methods:** rolling regressions on Ken French factors; shrinkage (Ledoit-Wolf 2004) when names ≈ observations; PCA for statistical factors. Full commercial risk models (Barra/Axioma) are paid; you can approximate the *risk-attribution* value with the above at meaningfully lower fidelity — state that limitation to users.

---

## 10. Trade-Stress-Testing Framework

The stress engine is arguably the strongest, most defensible part of this product (the math is honest and doesn't require predicting returns). Build three complementary modes:

### A. Historical scenario replay
Curate a library of dated episodes and apply each episode's factor/asset moves to the *current* position via its estimated betas + its own historical sensitivity:
- 1987 crash; 1998 LTCM; 2000–02 dot-com; 2008 GFC; 2010 Flash Crash; 2011 US downgrade; 2015-08 & 2018-02 vol spikes (incl. "Volmageddon"); 2018-Q4 selloff; **2020-02/03 COVID crash**; 2022 rate-shock/inflation bear; 2020-03 liquidity crisis; sector collapses (2014–16 energy, 2023 regional banks — SVB); short squeezes (2021 GME/AMC); commodity shocks (2022 oil/gas). Store each as a vector of factor returns + rates/commodity/FX/vol moves.
- Apply via: ΔP ≈ Σ βᵢ · (factor shockᵢ) + idiosyncratic gap assumption. Report both the factor-implied move and the stock's *own* realized behavior in that window if it existed then (respect survivorship — many names didn't exist).

### B. Hypothetical / sensitivity scenarios (user-configurable)
Market −X%; sector underperforms by Y%; vol doubles; correlations → 1 (diversification fails); revenue miss → margin compression → multiple contraction (chain the fundamentals→valuation); interest expense +Z (from leverage schedule); FX/commodity input shock; volume −50% & spread ×3 (liquidity); **overnight gap through the stop** (the single most important scenario for a stop-based trade). Each expressed as factor shocks + valuation re-rating.

### C. Statistical simulation
- **Historical simulation** (empirical return distribution — no distribution assumption).
- **Parametric** (Student-t to capture fat tails; **not** Gaussian for tails).
- **Block bootstrap** (preserve autocorrelation/vol-clustering — critical; i.i.d. bootstrap understates path risk).
- **Filtered historical simulation** (GARCH-standardized residuals, then re-inflate by current vol) — best free-data method for forward risk.
- **Factor-shock Monte Carlo** (simulate factor returns from their covariance, map through betas + idio).
- **Jump/gap modeling** (jump-diffusion or empirical overnight-gap distribution per name/sector) for earnings and event gaps.
- Outputs: **VaR and Expected Shortfall (ES/CVaR — coherent risk measure, Artzner et al 1999; Rockafellar-Uryasev)**, full **drawdown distribution**, **P(stop hit)**, **P(gap through stop)**, expected loss given gap.

### Long vs short must differ (High confidence)
- **Short-specific risks the engine must model explicitly:** unbounded/asymmetric loss (loss not capped at 100%); **borrow availability & cost** (hard-to-borrow, rising fees); **recall risk** (forced buy-in); **short-squeeze** (high SI + low float + high borrow + positive catalyst); **dividends owed** to lender; **upside gap risk** (worse for shorts — no natural ceiling). Convexity is inverted: shorts lose more as they move against you. Position sizing and stress distributions for shorts must be **asymmetric** (fatter right tail on losses). Borrow data is largely paid; **use short interest + float + days-to-cover as free proxies** and flag borrow uncertainty in the confidence layer.

---

## 11. Position-Sizing Research

**Core principle (High confidence): predicted return must NOT drive size on its own.** Return forecasts are the least reliable output; sizing on them concentrates risk exactly where the model is weakest and amplifies estimation error. Size on **risk**, cap by **conviction/edge**.

| Method | What it does | Use here | Caveat |
|---|---|---|---|
| Fixed fractional risk budget | Risk R% of equity per trade | Simple default | Ignores correlation |
| **Volatility targeting** | size ∝ target_vol / σ_stock | **Primary sizer** | Needs good σ (from §7) |
| **Stop-based sizing** | size = (risk $)/(entry − stop) | **Matches the user's stop input** | Assumes stop holds — combine w/ gap risk |
| **Expected-Shortfall constraint** | cap so position ES ≤ limit | **Tail-aware cap** | Needs tail model |
| Max-drawdown constraint | cap so contribution to portfolio MDD ≤ limit | Portfolio guardrail | Simulation-based |
| **Kelly / fractional Kelly** | size ∝ edge/variance; use ¼–½ Kelly | **Upper bound on size, not the target** | Full Kelly is too aggressive & needs accurate edge; fractional Kelly for estimation error |
| Risk parity | equalize risk contributions | Portfolio construction | For book, not single trade |
| Factor-risk limits | cap exposure per factor | Prevent crowded bets | Needs factor model |
| Liquidity/capacity | cap ≤ X% ADV; impact-aware | Hard cap | Corwin-Schultz spread + ADV |
| Concentration limits | max weight per name/sector | Guardrail | Governance |

**Recommended v1 sizer:** take the **minimum** of (vol-target size, stop-based size, ES-cap size, liquidity-cap size, fractional-Kelly ceiling, concentration limit). The binding constraint is shown to the user with the reason. This is transparent and safe. [Industry practice, High]

---

## 12. Complete Data-Source Ledger

**Verification status as of 2026-08-04. Re-verify at build time — terms change (see Alpha Vantage/Polygon/IEX below for how fast they move).**

### Tier 1 — Verified free & official (build on these)

**SEC EDGAR REST APIs — `data.sec.gov`** — **VERIFIED**
- Provider: U.S. SEC. Datasets: `companyfacts`, `companyconcept`, `frames` (XBRL financials), `submissions` (filing index); full-text search via `efts.sec.gov` (2001–present); bulk `companyfacts.zip`, `submissions.zip`; Financial Statement Data Sets (bulk XBRL).
- Variables: standardized XBRL fundamentals (income, balance sheet, cash flow), filing metadata, **Form 3/4/5 insider**, **13F holdings** (via filings).
- Depth: XBRL structured data ~2009+; filings back further; full-text 2001+. Update: intraday as filed. Delay: filing = public release (but note filing *timing* nuances, §13).
- API: **no key required.** **Rate limit: 10 requests/second per IP.** **Must send a descriptive `User-Agent` header with contact email** (else 403). Zero-pad CIK to 10 digits.
- Redistribution/commercial: public-domain US-government data (permissive). Point-in-time: **filing dates available → you can build PIT yourself; restatements require care.** Reliability: high; XBRL tagging inconsistencies across small filers/taxonomies.
- Suitable for: research, prototyping, production (with your own normalization). Backup: bulk zips; commercial (Sharadar/Compustat) for cleaned PIT.
- Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces ; https://www.sec.gov/os/accessing-edgar-data

**FRED (Federal Reserve Bank of St. Louis)** — **VERIFIED**
- Datasets: rates (Treasury yields, fed funds), inflation, credit spreads, macro series (controls only per scope). Depth: decades. Update: as released. 
- API: **free key** (email signup). Rate limit ~**120 req/min with key** (raised from 30). Redistribution: **free for non-commercial/educational/personal; commercial use has additional restrictions; scraping prohibited except via the API.** **⚠ Commercial-use caveat matters for a hedge-fund product — review FRED terms and, for underlying series, the original source's terms (some series are third-party/licensed).**
- Suitable: research/prototyping/production (as controls). Docs: https://fred.stlouisfed.org/docs/api/fred/ ; terms: https://fred.stlouisfed.org/legal/

**Kenneth R. French Data Library (Dartmouth)** — **VERIFIED**
- Datasets: FF3, **FF5**, Momentum (UMD/Mom), industry portfolios, size/BM portfolios — **daily & monthly factor returns**. Depth: 1926+ (monthly), 1963+ (daily for many). Update: periodic.
- API: static CSV/ZIP downloads (no formal API; several free wrappers). Redistribution: academic library; check page terms before redistributing. 
- Suitable: research/prototyping/production benchmark factors. **This is your free factor-return backbone.** Docs: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

**FINRA — Equity Short Interest & Daily Short-Sale Volume** — **VERIFIED**
- Datasets: **biweekly short interest** (Rule 4560; all exchange-listed + OTC), **daily short-sale volume** files. Depth: archives to 2014 (short interest). Delay: short interest reported twice monthly with a settlement/publication lag (~8 business days). 
- API/access: downloadable pipe-delimited files + data portal + a file-download API (metadata PDF exists). Redistribution: FINRA terms — check. Suitable: research/prototyping/production (with lag awareness).
- Docs: https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files ; https://www.finra.org/filing-reporting/short-interest

**OpenFIGI (Bloomberg)** — **VERIFIED (with caveat)**
- Use: identifier mapping (ticker/ISIN/SEDOL/CUSIP → **FIGI**). Free API; higher limits with free key (reported ~25k jobs/min with key; lower unauthenticated, ~5k/day figure cited). 
- **⚠ Caveat:** FIGI mapping is free and open, but **CUSIP/ISIN themselves are licensed identifiers** (CUSIP Global Services / FactSet; ISIN via national numbering agencies). You may map *to* FIGI freely; **redistributing CUSIPs may require a licence.** Use FIGI + SEC CIK as your free internal keys. Docs: https://www.openfigi.com/api/documentation

**CBOE — VIX & index data** — **VERIFIED (partial)**
- Free: **VIX index history (1990+ close; OHLC 1992+)**, VIX futures (2004+). **Not free:** historical *option chains* / per-name options (CBOE DataShop — paid). Suitable: VIX as a market-vol/stress input; per-name options → paid/defer. Docs: https://www.cboe.com/tradable_products/vix/vix_historical_data/

### Tier 2 — Free tiers usable for prototyping (limits are tight; VERIFY at build)

**Polygon.io (now "Massive")** — **VERIFIED**
- **Rebranded to Massive.com on 2025-10-30** (polygon.io/pricing → massive.com/pricing; API/keys unchanged). Free: **5 API calls/min, EOD + 15-min-delayed** stock data, no card. Paid from ~$199/mo (real-time/higher limits). Good corporate-actions & aggregates. Suitable free: prototyping only (not live). Docs: https://massive.com/pricing (formerly polygon.io/docs)

**Financial Modeling Prep (FMP)** — **VERIFIED**
- Free: **250 requests/day**, EOD historical, profile/reference, 150+ endpoints; legacy vs new endpoint split. Paid tiers for depth/real-time. **⚠ Fundamentals are convenient but quality/PIT-integrity is not audited — treat as prototyping, cross-check vs SEC XBRL.** Suitable: prototyping. Docs: https://site.financialmodelingprep.com/pricing-plans

**Finnhub** — **VERIFIED**
- Free: **60 calls/min**; US real-time quotes, company news, **basic** fundamentals, filings, 50-symbol websocket. Depth of free fundamentals is limited; premium for full financials/estimates. Suitable: prototyping (news/quotes/basic fundamentals). Docs: https://finnhub.io/pricing ; https://finnhub.io/docs/api/rate-limit

**Tiingo** — **VERIFIED (nuance)**
- Free/personal tier: EOD prices (30+yr history), ~**500 unique symbols/month** with per-hour/day request caps; **5yr fundamentals** on free; **fundamentals now largely a paid add-on via a third-party provider**. (One source cited "20 calls/day on demo tickers" for unregistered demo — the registered free tier is more generous; **verify current limits**.) Suitable: prototyping, small research. Docs: https://www.tiingo.com/about/pricing

**Alpha Vantage** — **VERIFIED**
- Free: **25 requests/day, 5/min** (was 500 → 100 → **25**; illustrates how fast free tiers shrink). Provides prices, some fundamentals, FX/crypto, technical indicators. **Too limited for anything but tiny prototyping.** Paid removes daily cap. Docs: https://www.alphavantage.co/premium/

**Stooq** — **VERIFIED**
- Free EOD CSV (world stocks/indices/futures, 20+yr). **No official API** (undocumented CSV URLs work but are unsupported/fragile). Redistribution/terms unclear — **UNVERIFIED licence**. Suitable: research/backup EOD only. https://stooq.com

**Nasdaq Data Link (ex-Quandl)** — **PARTIALLY VERIFIED**
- Some free datasets remain; **premium datasets (incl. Sharadar) are paid.** Sharadar SF1/SEP/etc. = **high-quality, point-in-time, survivorship-free US fundamentals & prices** — the most cost-effective *paid* upgrade for a serious backtest (see §15). Retirement of specific free datasets over time is common — **UNVERIFIED which free sets persist as of 2026**; check the catalog. Docs: https://data.nasdaq.com ; https://sharadar.com

### Tier 3 — Do NOT build on
- **IEX Cloud — DEAD.** Retired **2024-08-31**; all endpoints off. Many tutorials still reference it — ignore them. https://iexcloud.org
- **yfinance / undocumented Yahoo Finance endpoints** — unofficial; **Yahoo ToS restricts to personal use, no redistribution/commercial use**; endpoints change without notice and get blocked; **not affiliated with Yahoo.** Fine for personal exploration; **not for a production hedge-fund product** (legal + reliability risk). Treat any Yahoo-derived data as **UNVERIFIED for commercial use.**

### Data needed vs. best free source (summary)
| Need | Best free/official | Paid upgrade | Notes |
|---|---|---|---|
| Prices/volume (EOD) | Polygon/Massive free, Stooq, Tiingo | Polygon/Massive, Databento, Nasdaq | Free = delayed/EOD only |
| Prices (intraday/real-time) | **None adequate free** | Polygon/Massive, Databento, Alpaca | **Excludes intraday from v1** |
| Corporate actions | Polygon/Massive; SEC 8-K | Sharadar, Norgate | Verify split/div accuracy |
| **Delisted / survivorship-free** | **Weak free coverage** | **Sharadar, CRSP (WRDS), Norgate** | **Biggest free-data gap** |
| Fundamentals | **SEC XBRL (build PIT yourself)** | Sharadar SF1, Compustat | Free = you do the cleaning |
| SEC filings / XBRL | **SEC EDGAR** | sec-api.io convenience | Native is free |
| Earnings dates/actuals | FMP/Finnhub free (limited) | Sharadar, Zacks, Wall St Horizon | Verify timing (PIT!) |
| Analyst estimates/revisions | **Poor free coverage** | I/B/E/S (WRDS), Zacks, FactSet | Revisions signal needs paid |
| Insider transactions | **SEC Form 4** | 2iQ, InsiderScore | Native is free |
| Institutional holdings | **SEC 13F** (≥45-day lag) | WhaleWisdom, FactSet | Lag is inherent |
| Short interest | **FINRA** (biweekly) | S3, IHS Markit (borrow) | Borrow cost = paid |
| Options / implied vol | VIX free; per-name paid | ORATS, OptionMetrics (WRDS), CBOE DataShop | Defer per-name |
| News/sentiment | Finnhub free (limited); LM lexicon free | RavenPack, Bloomberg | NLP as feature only |
| Sector/industry | SIC (SEC) free; **GICS licensed** | GICS (MSCI/S&P) | Use SIC or free GICS-approx |
| Factor returns | **Ken French** | AQR datasets (some free), Barra | French is enough for v1 |
| Risk-free / benchmarks | **FRED**; French RF | — | Free |
| Academic anomaly data | AQR Data Library (free); Open Source Asset Pricing (Chen-Zimmermann) | — | **OSAP is a gold mine — see §17** |

**Where professional data is realistically required (High confidence):** survivorship-free/delisted history, point-in-time fundamentals, analyst-estimate revisions, per-name options-implied vol, borrow cost/availability, real-time/intraday prices, and licensed classifications (GICS)/identifiers (CUSIP). Plan to run v1 on free data for *research and paper trading only*, and gate any real-capital use on at least Sharadar-level PIT data.

---

## 13. Point-in-Time & Bias-Control Requirements

**The timestamp taxonomy every datum must carry (High confidence — this is the backbone of PIT integrity):**
1. **Fiscal period end** (what the number describes).
2. **Filing date** (when submitted to SEC).
3. **Public release timestamp** (press release / accepted timestamp — may precede or follow filing; earnings often pre-announced before the 10-Q).
4. **Data-provider ingestion time** (when *your* pipeline could have had it).
5. **Model-availability time** (when the feature is computable, after your batch runs).
6. **Trade-execution time** (when you could act — typically next open/close after availability).

**Rule:** features for a decision at time *t* may use only data with public-release/ingestion ≤ *t*, and returns are measured from execution time *after* availability (add a realistic lag, e.g., trade at next close after data is public). Never use fiscal-period-end as the availability date — that is the classic look-ahead error.

**Biases and how to prevent each:**
| Bias | Cause | Prevention |
|---|---|---|
| Look-ahead | Using data before it was public | Enforce timestamp taxonomy above; lag fundamentals to filing/release date |
| Survivorship | Universe = today's survivors | **Reconstruct historical universe including delisted names**; hardest free-data problem → paid data or explicit caveat |
| Delisting | Dropping dead tickers / ignoring delist returns | Include delisting returns (often −30% to −100% for bankruptcies); CRSP/Sharadar have them |
| Restatement leakage | Using restated (revised) fundamentals as if known then | Use **as-first-reported** values (SEC original filing), not later amendments |
| Fundamental revision leakage | Vendor overwrites history | Store immutable, versioned snapshots; prefer as-first-reported |
| Earnings-timing error | Assuming report available at period end | Use actual release timestamp; many misses come from this |
| Corporate-action error | Wrong split/div adjustment | Keep raw + adjusted; validate against multiple sources |
| Time-zone error | Mixing exchange/UTC | Normalize to exchange local + store UTC |
| Index-membership look-ahead | Using today's S&P 500 historically | Use **historical constituents as-of date** (licensed data or reconstruct) |
| Classification look-ahead | Today's GICS/sector applied to past | Store point-in-time classifications |
| Data-snooping / multiple testing | Trying many signals, reporting the winner | **Track # trials; Deflated Sharpe; holdout; pre-registration of hypotheses** (§11, §17) |

---

## 14. Backtesting & Validation Protocol

**Validation design (High confidence):**
- **Walk-forward / expanding-window**, never random k-fold on time series.
- **Purged K-fold + embargo** (López de Prado 2018) when using overlapping labels (any multi-day forward return): purge training samples whose label window overlaps the test set; embargo a gap after each test fold. **Combinatorial Purged CV (CPCV)** for more robust path distributions in v2+.
- **Untouched final test period** (lockbox): decided once, never iterated on.
- **Cross-sectional validation** (rank-IC per date), not just pooled.
- **Uniqueness/overlap weighting** for overlapping labels (sample weights ∝ label uniqueness).

**Realistic universe & execution:**
- Reconstruct universe *as-of each date* incl. delisted; apply liquidity filters as-of date.
- Execute at **next available price after signal is public** (avoid same-bar fills).
- Costs: **bid-ask spread (Corwin-Schultz from OHLC if no quotes), commissions, slippage, market impact (square-root law), borrow fees (shorts), dividends, turnover.** Report **net** of all.
- **Capacity analysis:** cap trades at % of ADV; show how returns decay with AUM.

**Statistical rigor:**
- **Multiple-hypothesis testing:** count every variant tried; apply **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) and/or Harvey-Liu-Zhu haircuts; report **Probability of Backtest Overfitting (PBO)**.
- **Feature & model ablation**, **sensitivity testing** (params ± ranges), **stability** across time, sectors, market-cap buckets, and vol regimes.
- **Calibration** (for probabilistic outputs): reliability curves, Platt/isotonic recalibration.

**Metrics (report a panel, never cumulative return alone — High confidence):**
- Signal: **IC, Rank-IC** (mean, std, IR of IC), quantile spread (top-vs-bottom decile), hit rate.
- Probabilistic: **Brier, log-loss, calibration error, AUC**.
- Point: MAE (not R² alone — it's tiny and misleading here).
- Portfolio: **Sharpe, Sortino, Information Ratio, max drawdown, ES, turnover, return per unit turnover, factor-adjusted alpha (regress returns on FF5+MOM), and Deflated Sharpe.**
- Vol models: QLIKE / MSE vs realized; VaR/ES backtests (Kupiec unconditional coverage, Christoffersen conditional coverage).

**Explicit anti-patterns to forbid in the spec:** evaluating on cumulative backtest return; random shuffling of time series; reusing the lockbox; reporting only the best of many trials without a deflation correction; in-sample-only claims.

---

## 15. Monitoring & Model-Governance Framework

**Runtime data hygiene:** schema/range validation, staleness checks, cross-source reconciliation, missing-data handling → the **confidence layer** downgrades or **abstains** when data is stale/missing/contradictory/out-of-distribution.

**Model monitoring:**
- **Feature drift** (PSI/KL divergence vs training distribution).
- **Prediction-distribution monitoring** (are scores shifting?).
- **Calibration monitoring** (rolling Brier/reliability).
- **Performance decay** (rolling IC/Sharpe with alerts) — expect decay (McLean-Pontiff).
- **Retraining triggers** (scheduled + drift/decay-triggered).

**Release governance:**
- **Champion/challenger** and **shadow testing** (new model runs silently alongside prod before promotion).
- **Model & dataset versioning** (immutable snapshots; reproducible from lineage store).
- **Audit logs** (every output → inputs, as-of timestamps, model version, confidence).
- **Automated regression tests**; **safe rollback**; **failure alerts**.
- **Insufficient-data / OOD responses:** system must **abstain from a confident conclusion** and say why (this is a first-class output, not an error).
- **Human approval gate** for any action with real capital and for promoting models.

---

## 16. Free-Data Limitations & Paid-Data Upgrade Path

**Hard limits of the free stack (High confidence):**
- No adequate intraday/real-time.
- Survivorship-free/delisted history is the critical gap → **any backtest on free survivor-only data overstates returns** (often by several %/yr).
- PIT fundamentals must be hand-built and are error-prone at scale.
- No free analyst-revision, borrow-cost, or per-name options data.
- Licensed identifiers (CUSIP) and classifications (GICS) constrain redistribution.
- Commercial-use terms (FRED, Yahoo, vendor free tiers) may **prohibit a for-profit hedge-fund product** — a legal review is required before real deployment.

**Recommended upgrade sequence (cost-ordered):**
1. **Sharadar (via Nasdaq Data Link)** — PIT, survivorship-free US fundamentals + prices + actions; the highest ROI first paid upgrade for honest backtests (low hundreds $/mo range — **verify current pricing**).
2. **A real price/corporate-action feed** (Polygon/Massive paid or Databento) for clean adjusted history + eventual intraday.
3. **Analyst estimates/revisions** (I/B/E/S via WRDS if academic access, else Zacks) — unlocks the revisions anomaly.
4. **Borrow cost/availability** (S3/IHS Markit) — required before running real short books.
5. **Options-implied** (ORATS / OptionMetrics via WRDS) — for skew/IV features.
6. **CRSP + Compustat (WRDS)** — the academic gold standard if any partner has university access.

---

## 17. Key Mathematical Formulas & Pseudocode

**Volatility (EWMA / RiskMetrics):**
σ²_t = λ·σ²_{t−1} + (1−λ)·r²_{t−1},  λ≈0.94 (daily). 

**GARCH(1,1):** σ²_t = ω + α·r²_{t−1} + β·σ²_{t−1};  **GJR-GARCH** adds γ·r²_{t−1}·1[r_{t−1}<0] (leverage).

**Factor exposure (rolling, ridge-shrunk):**
r_i − r_f = α_i + Σ_k β_{i,k}·F_k + ε_i;  β̂ = (XᵀX + λI)⁻¹ Xᵀy.

**Fama-MacBeth:** for each t, regress cross-section r_{i,t} on characteristics X_{i,t−1} → γ_t; premium = mean_t(γ_t), t-stat from time-series of γ_t (Newey-West SE).

**Cross-sectional composite score (baseline ranking):**
z_{i,s} = (x_{i,s} − median_s)/MAD_s (winsorize first); sector-neutralize by subtracting sector mean; Score_i = Σ_s w_s·z_{i,s}; rank → percentile.

**Information Coefficient:** IC_t = corr(score_{·,t}, fwd_ret_{·,t}); **Rank-IC** = Spearman. IR_of_IC = mean(IC)/std(IC)·√periods.

**VaR / Expected Shortfall (historical):** VaR_α = −quantile_α(P&L); **ES_α = −E[P&L | P&L ≤ −VaR_α]** (coherent).

**Deflated Sharpe Ratio (Bailey–López de Prado 2014):** deflate observed SR by the expected maximum SR under N independent trials (accounts for skew, kurtosis, sample length, and # trials) → probabilistic significance. Use as the go/no-go gate for any strategy claim.

**Corwin-Schultz spread (from daily high/low):** estimate effective spread from 1- and 2-day high-low ranges (β and γ terms) — gives a spread proxy without quote data.

**Position size (v1) — take the binding minimum:**
```
size = min(
  vol_target_equity * target_vol / sigma_stock,      # vol targeting
  risk_budget_$ / (entry - stop),                     # stop-based
  size_such_that(position_ES <= ES_limit),            # tail cap
  fraction_kelly * (edge / variance),                 # Kelly ceiling (frac<=0.5)
  max_pct_ADV * ADV / entry,                          # liquidity cap
  max_name_weight * equity / entry                    # concentration cap
)
report(binding_constraint)   # tell the user WHY this size
```

**Stress engine (pseudocode):**
```
for scenario in (historical_episodes ∪ hypotheticals):
    factor_shock = scenario.factor_returns            # incl. rates/FX/commodity/vol
    dP_systematic = sum(beta_k * factor_shock_k)
    dP_idio       = sample_gap(name, scenario)         # empirical/jump, asymmetric for shorts
    revalue via valuation_chain if fundamental scenario # miss->margin->multiple
    pnl = position_value * (dP_systematic + dP_idio) * side  # side=+1 long,-1 short
    record(pnl)
distribution = statistical_sim(historical | FHS | block_bootstrap | factor_MC)
report(VaR, ES, drawdown_dist, P(stop_hit), P(gap_through_stop), worst_case)
```

**Purged K-fold CV (labels over [t, t+h]):** remove from train any sample whose [t, t+h] overlaps the test window; embargo an extra buffer after test; weight samples by label uniqueness.

---

## 18. Research Disagreements & Unresolved Questions

1. **Is there a "replication crisis" in factors?** Hou-Xue-Zhang (2020, *Replicating Anomalies*) find ~50–65% of anomalies fail to replicate with proper methods (esp. equal-weight/microcap-driven ones). Harvey-Liu-Zhu (2016) demand t-stats ≳3 for new factors. **But** Jensen-Kelly-Pedersen (2023, JF, *Is There a Replication Crisis in Finance?*) argue most factors *do* replicate under a Bayesian/hierarchical lens. **Implication:** favor the *most robust, mechanism-backed* factors (value, momentum, quality/profitability, low-vol, investment, PEAD, net issuance); treat the long tail of the "factor zoo" as noise. Use the **Open Source Asset Pricing dataset (Chen & Zimmermann)** to sanity-check any signal's post-publication behavior. [Academic, High that caution is warranted]
2. **Does momentum survive at small scale after costs?** Yes gross; net is eroded by turnover; crash risk (2009) is severe. Requires vol-scaling / dynamic momentum (Barroso-Santa-Clara 2015). [Contested → Medium]
3. **Short-term reversal:** real but largely a liquidity-provision premium → costs eat it at retail scale. [Medium]
4. **Are cross-sectional characteristics best combined linearly or via ML?** Gu-Kelly-Xiu (2020, RFS) show ML (trees/NN) adds value in large panels; others show fragility/overfit. **Recommendation:** linear/composite baseline; ML only if it beats it on purged CV + DSR. [Contested]
5. **Best distress model:** Campbell-Hilscher-Szilagyi (2008) generally beats Altman Z / Ohlson O out-of-sample, but all degrade in new regimes. [Medium-High]
6. **How much does 13F/insider data help after lags?** Modest and easy to overweight; treat as context, not signal. [Low-Medium]
7. **Commercial-use licensing** of FRED-derived and vendor free-tier data for a for-profit fund — **UNVERIFIED / needs legal review.**

---

## 19. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Survivorship/PIT leakage inflates backtest** | High | Critical | PIT layer; delisted universe; as-first-reported; lockbox |
| **Multiple-testing overfitting** | High | Critical | DSR, PBO, trial counting, holdout, pre-registration |
| Free data ends / ToS change (Yahoo/AV/Polygon) | High | High | Abstract data layer behind adapters; multi-source; budget for paid |
| Commercial-use licence breach | Medium | High (legal) | Legal review before real capital; prefer public-domain (SEC) sources |
| Users treat output as advice / profit promise | High | High (compliance) | Framing as evidence/risk; disclaimers; abstention; no profit language |
| Corporate-action errors | Medium | High | Dual raw/adjusted; cross-source validation |
| Short-book blowup (squeeze/borrow) | Medium | Critical | Asymmetric short stress; SI/float/DTC flags; borrow-uncertainty in confidence |
| Model decay unnoticed | High | Medium | Rolling IC/calibration monitors; retraining triggers |
| LLM hallucination presented as quant | Medium | High | LLM confined to explanation layer; cite numeric provenance only |
| Regime shift breaks stationarity assumptions | High | High | Regime-aware stress; OOD abstention; walk-forward |
| Small-team capacity / scope creep | High | Medium | MVP discipline; earn complexity |

---

## 20. Recommended MVP → Phase 2 → Advanced

**MVP (v1):** free-data (SEC EDGAR, FRED, Ken French, FINRA, one EOD price adapter, OpenFIGI). Layers 1–18 in transparent form. Baseline = **EWMA vol + rolling factor betas + sector-neutral z-score composite ranking + valuation/quality/distress panels + historical & Monte-Carlo stress + risk-based sizing + confidence/abstention + LLM explanation/adversarial-thesis.** Horizons: 1–5d, swing, 3–12m. **Research/paper-trading only.** Rigorous purged-CV + DSR harness from day one.

**Phase 2:** Sharadar PIT data; GARCH/GJR vol + DCC; probabilistic P(target-before-stop) with triple-barrier + purging; earnings-surprise-direction model; Bayesian shrinkage into confidence; fundamental (Barra-style) risk model; champion/challenger + shadow testing; analyst-revision features (paid).

**Advanced:** LightGBM cross-sectional ranker (gated by DSR); regime-conditional stress; options-implied features (paid); NLP on filings/calls ("Lazy Prices," LM sentiment) as features; capacity/impact-aware portfolio construction; borrow-feed integration for live shorts.

---

## 21. Bibliography (direct links; dates noted)

**Data / official docs (all verified 2026-08-04):**
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces ; access rules: https://www.sec.gov/os/accessing-edgar-data
- FRED API: https://fred.stlouisfed.org/docs/api/fred/ ; terms: https://fred.stlouisfed.org/legal/
- Ken French Data Library: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- FINRA short interest: https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files
- OpenFIGI: https://www.openfigi.com/api/documentation
- CBOE VIX data: https://www.cboe.com/tradable_products/vix/vix_historical_data/
- Polygon/Massive pricing: https://massive.com/pricing (rebrand 2025-10-30)
- FMP pricing: https://site.financialmodelingprep.com/pricing-plans
- Finnhub: https://finnhub.io/pricing
- Tiingo: https://www.tiingo.com/about/pricing
- Alpha Vantage: https://www.alphavantage.co/premium/
- IEX Cloud (retired 2024-08-31): https://iexcloud.org
- Sharadar / Nasdaq Data Link: https://sharadar.com ; https://data.nasdaq.com
- Open Source Asset Pricing (Chen & Zimmermann): https://www.openassetpricing.com/
- AQR Data Sets (free factor data): https://www.aqr.com/Insights/Datasets

**Methodology (canonical; verify DOIs as needed):**
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, JPM — SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- López de Prado (2018), *Advances in Financial Machine Learning* (purged CV, CPCV, triple-barrier, sample uniqueness).
- Harvey, Liu & Zhu (2016), *…and the Cross-Section of Expected Returns*, RFS.
- Hou, Xue & Zhang (2020), *Replicating Anomalies*, RFS: https://www.nber.org/papers/w23394
- Feng, Giglio & Xiu (2020), *Taming the Factor Zoo*, JF: https://dachxiu.chicagobooth.edu/download/ZOO.pdf
- Jensen, Kelly & Pedersen (2023), *Is There a Replication Crisis in Finance?*, JF: https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- McLean & Pontiff (2016), *Does Academic Research Destroy Stock Return Predictability?*, JF.

**Signals (canonical):** Fama-French (1992/1993, 2015); Jegadeesh-Titman (1993); Daniel-Moskowitz (2016); Novy-Marx (2013); Asness-Frazzini-Pedersen QMJ (2019); Frazzini-Pedersen BAB (2014); Ang-Hodrick-Xing-Zhang (2006); Sloan (1996); Piotroski (2000); Altman (1968); Ohlson (1980); Campbell-Hilscher-Szilagyi (2008); Beneish (1999); Pontiff-Woodgate (2008); Bernard-Thomas (1989/90); Chan-Jegadeesh-Lakonishok (1996); Cohen-Malloy-Nguyen (2020, *Lazy Prices*); Loughran-McDonald (2011); Amihud (2002); Corwin-Schultz (2012); Ledoit-Wolf (2004); Gu-Kelly-Xiu (2020); Grinold-Kahn (*Active Portfolio Management*); Artzner et al (1999, coherent risk); Rockafellar-Uryasev (CVaR).

*(Signal papers cited by author/year/journal for the architect to pull via the links above or a library; primary DOIs should be confirmed at spec time.)*

---

## 22. Instructions and Evidence for the System Architect

**Strongest supported recommendations (build on these):**
1. **Separate the layers; never emit one opaque score.** Each layer outputs value + uncertainty + provenance. [High]
2. **Make the baseline a transparent, sector-neutral, cross-sectional z-score ranking** validated by rank-IC — not price/return point prediction. [High]
3. **Build volatility first** (EWMA→GARCH); it's the most forecastable quantity and powers sizing + stress. [High]
4. **Position sizing on risk, capped by conviction — never on return forecast alone.** Take the binding minimum of vol/stop/ES/liquidity/Kelly/concentration constraints. [High]
5. **The stress engine is the product's strongest, most honest feature.** Invest there; make long/short asymmetric; always simulate the overnight-gap-through-stop. [High]
6. **Enforce PIT integrity structurally** via the six-timestamp taxonomy and as-of data access. [High]
7. **Gate every strategy claim on purged CV + Deflated Sharpe + trial counting.** [High]
8. **Confine the LLM to explanation/adversarial-thesis; it never touches the numeric engine.** [High]
9. **Confidence layer must be able to abstain** on stale/missing/contradictory/OOD data. [High]

**Decisions that still require human judgment (do not let the model pick silently):**
- Exact universe/liquidity floors; horizon definitions; factor set finalization; signal weights in the composite; risk limits (target vol, ES limit, max weights, Kelly fraction); whether to buy Sharadar before any real-capital use; and the **legal review of commercial-use terms.**

**Claims that need independent verification before coding:**
- Current free-tier limits/pricing for **every** vendor (they move fast — Alpha Vantage 500→25, Polygon→Massive rebrand, IEX death all happened recently).
- Sharadar current pricing and which Nasdaq Data Link free datasets still exist. **[UNVERIFIED as of 2026-08-04]**
- Tiingo exact free-tier request/symbol caps (sources conflicted). **[Partially UNVERIFIED]**
- Whether FRED/Yahoo/vendor terms permit a **for-profit** product. **[UNVERIFIED — legal]**
- Exact DOIs/links for signal papers (cited by author/year here).

**Data sources successfully verified (free/official):** SEC EDGAR (`data.sec.gov`, `efts.sec.gov`; 10 req/s, User-Agent required); FRED (free key, ~120 req/min, non-commercial terms); Ken French Data Library; FINRA short interest; OpenFIGI (with CUSIP-licensing caveat); CBOE VIX (index/futures free, options paid); Polygon/Massive free tier (5/min, EOD/15-min); FMP (250/day); Finnhub (60/min); Alpha Vantage (25/day); Stooq (EOD CSV, no API, licence unclear).

**Data sources that could NOT be fully verified:** which Nasdaq Data Link free datasets persist; exact Sharadar 2026 pricing; exact Tiingo free caps; Stooq licence/redistribution terms; commercial-use permissibility of several free feeds. All marked UNVERIFIED above.

**Recommended defaults for unanswered project questions:**
- **Horizons:** ship 1–5d, swing (2–6wk), 3–12m; **exclude intraday** (data) and **multi-year** (validation) from v1.
- **Separate models per horizon?** Yes — at minimum separate *labels/targets* and *feature horizons* per bucket; can share infrastructure but not one blended target. [High]
- **Target:** cross-sectional sector-neutral excess-return **rank**.
- **Baseline model:** transparent composite + rolling factor betas + EWMA vol.
- **Universe:** liquid US common stock + ETF benchmarks only.
- **Deployment posture:** research/paper-trading until PIT data + legal review are in place.

**The most dangerous forms of leakage/overfitting to guard against (in priority order):**
1. **Point-in-time / look-ahead** in fundamentals and index/sector membership (using restated data or future constituents).
2. **Survivorship / delisting** bias from a survivor-only universe.
3. **Multiple-testing / backtest overfitting** (picking the best of many trials without deflation).
4. **Overlapping-label leakage** in path-dependent targets (fix with purging/embargo/uniqueness weighting).
5. **Cost-blind backtests** (spreads, impact, borrow, turnover) that turn paper alpha into real losses.

**What the next model MUST preserve when writing the engineering spec:**
- The **layered, inspectable architecture** with per-layer uncertainty and provenance.
- The **PIT timestamp taxonomy** and as-of data access as a hard constraint.
- The **validation harness (purged CV + DSR + lockbox + cost model)** as non-negotiable infrastructure, not an afterthought.
- **Risk-based sizing** and the **abstention/confidence** mechanism.
- The **LLM boundary** (explanation only).
- A **data-adapter abstraction** so any vendor can be swapped when free tiers change or paid upgrades arrive.
- Honest **framing**: a risk-and-evidence engine, never a profit-prediction or advice machine.

---

*End of dossier. Prepared in research-only mode; no application code produced. All data-provider terms are time-sensitive and must be re-verified at implementation. Items marked UNVERIFIED require independent confirmation before they drive engineering or capital decisions.*
