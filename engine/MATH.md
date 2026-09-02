# Incepta Engine — Formula Reference & Worked Examples

Every formula the engine uses, checked against its primary definition, with a
worked "real-time" example for each. This is the audit record and the reference
for the independent reviewer.

**Audit result (2026-08-12):** all modules checked formula-by-formula. Two real
issues found and fixed: (1) downside deviation used a non-standard denominator;
(2) the Deflated Sharpe crashed on `n_trials=1`. Three fitting extras added:
Value-at-Risk, Expected Shortfall, and Blume beta shrinkage. Documented
simplifications are listed at the end. Tests: 23/23 green.

Notation: `r_t` = daily simple return; `R̄` = mean; `σ` = std dev; annualization
uses 252 trading days.

---

## 1. Returns & Momentum  (`features/returns.py`)

**Daily simple return:** `r_t = P_t / P_{t-1} − 1`
> Example: close 110 after 100 → r = 110/100 − 1 = **+10%**.

**Cumulative return over k bars:** `P_t / P_{t−k} − 1`
> Example: price 290 today vs 261 a month (21 bars) ago → 290/261 − 1 = **+11.1%**.

**Momentum 12-1 (Jegadeesh-Titman 1993):** return from ~12 months ago to ~1 month
ago, *skipping the most recent month* (recent month reverses, so it's excluded).
`P_{t−21} / P_{t−252} − 1`
> Example: price 200 (≈252 trading days ago) → 290 (≈21 days ago) = **+45%**
> momentum. (Real AAPL run: +49.3%.)

**Short-term reversal:** the recent 1-month return; the *signal* is its negative
(recent winners tend to pull back). We return the raw return; the scorer flips the
sign via a negative weight.

---

## 2. Risk & Volatility  (`features/returns.py`, `models/volatility.py`, `validation/metrics.py`)

**Realized volatility (annualized):** `σ(r) × √252` using sample std (ddof=1).
> Example: daily std 2.0% → 0.02 × √252 = **31.7%/yr**. (Real AAPL: 32.0%.)

**Downside deviation (target semi-deviation, target 0) — FIXED:**
`√( (1/N) · Σ min(r_t, 0)² ) × √252`
Only negative days contribute to the sum, but we divide by the **total** N (the
standard Sortino definition), not by the count of negatives.
> Example: returns [+1%, −2%, +1.5%, −1%] → downside [0, −2%, 0, −1%];
> mean-square = (0.0004+0.0001)/4 = 0.000125; √ = 1.118%/day → **17.7%/yr**.
> (This is why a roughly symmetric stock's downside vol sits *below* its total
> vol — the old code divided by negatives only and wrongly produced a larger
> number than total vol.)

**EWMA volatility (RiskMetrics, λ=0.94):** `σ²_t = λ·σ²_{t−1} + (1−λ)·r²_{t−1}`
Recent moves get more weight, so vol reacts to fresh shocks.
> Example: yesterday σ = 2.0%/day (σ²=0.0004); yesterday's move was −3% (r²=0.0009).
> σ²_t = 0.94·0.0004 + 0.06·0.0009 = 0.00043 → σ_t = 2.07%/day → **32.9%/yr**
> (vol ticked up after the big down day).

**Maximum drawdown:** worst peak-to-trough decline = `min_t(P_t / max_{s≤t}P_s − 1)`.
> Example: peak 100, later trough 80 → **−20%**.

**Value-at-Risk (historical, EXTRA added):** the loss not exceeded with prob α, as
a positive number: `VaR_α = −quantile_{1−α}(r)`.
> Example: 95% VaR of a daily series whose 5th percentile is −2.5% → **VaR = 2.5%**
> ("on 5% of days you lose more than 2.5%").

**Expected Shortfall / CVaR (coherent, EXTRA added):** average loss in the worst
(1−α) tail: `ES_α = −mean( r | r ≤ quantile_{1−α} )`. Always `ES ≥ VaR`.
> Example: same series, the worst 5% of days average −3.8% → **ES = 3.8%**.

**52-week-high ratio:** `P_t / max(P over trailing 252)`. 1.0 = at the high.
> Example: 303 today vs 340 high → 303/340 = **0.89** (11% below the high).

**Amihud illiquidity (2002):** average of `|r_t| / dollar_volume_t`. Higher = price
moves more per dollar traded (less liquid). *Convention: often ×10⁶ for readability;
we keep it raw since only the cross-sectional ordering matters.*

**Corwin-Schultz spread from daily high/low (2012):** estimates the bid-ask spread
without quote data. With `β = ln(H_t/L_t)² + ln(H_{t−1}/L_{t−1})²`,
`γ = ln(H²ᵈ/L²ᵈ)²` (2-day high/low), `k = 3 − 2√2`:
`α = (√(2β) − √β)/k − √(γ/k)`, `S = 2(eᵅ − 1)/(1 + eᵅ)`, floored at 0.
> Interprets a wide daily range as evidence of a wider spread. *Known to overstate
> for very liquid names* — treat as a rough upper bound, not a quoted spread.

---

## 3. Factor Model & Risk Decomposition  (`models/factor.py`)

**Time-series factor regression (Fama-French 5 + Momentum):**
`r_i − r_f = α + β_mkt·MKT + β_smb·SMB + β_hml·HML + β_rmw·RMW + β_cma·CMA + β_mom·MOM + ε`
Estimated by (optionally ridge-penalised) least squares over a rolling window.

- **β_k** = sensitivity to factor k. **α** = return unexplained by factors (×252 to annualize).
- **R²** = fraction of the stock's variance explained by the factors.
- **Idiosyncratic vol** = `σ(ε) × √252`, using residual dof (N − #params).

> Example (real NVDA, 252 days): β_mkt = 1.46, β_mom = +0.30, R² = 0.62, idio vol
> 22%. **Real-time read:** on a day the market excess is +2% (other factors ~0),
> NVDA's expected excess ≈ 1.46 × 2% = **+2.9%**; 62% of its swings are
> factor-driven, 38% is stock-specific (the 22% idio vol).

**Blume beta shrinkage (1971, EXTRA added):** `β_adj = ⅔·β_raw + ⅓·1.0`. A
one-window beta is noisy and betas mean-revert toward 1; the shrunk beta predicts
*future* beta better. Market beta only.
> Example: raw β 1.6 → adjusted **1.4**.

**Ridge shrinkage:** `β = (XᵀX + λI)⁻¹Xᵀy` with the intercept left unpenalised —
stabilises betas when factors are collinear or the window is short.

---

## 4. Valuation  (`models/valuation.py`)

All guard their denominator and return `null` (not a fake number) when meaningless.

`Market cap = price × shares`; `P/E = MktCap / NetIncome` (only if NI>0);
`Earnings yield = NI / MktCap`; `P/B = MktCap / Equity`; `P/S = MktCap / Revenue`;
`FCF = OCF − |Capex|`, `FCF yield = FCF / MktCap`;
`EV = MktCap + LongTermDebt − Cash`, `EV/Sales = EV / Revenue`.

> Example: price 300, shares 15.0B → MktCap 4.5T. NI 100B → **P/E 45**, earnings
> yield 2.2%. Equity 65B → **P/B 69** (rich). Revenue 400B → **P/S 11.3**. If NI
> were negative, P/E returns null + flag "negative earnings → P/E not meaningful".
> Banks/REITs get a sector flag (P/E and EV unreliable there).

---

## 5. Quality & Distress  (`models/quality.py`)

**Piotroski F-score (2000), 9 binary signals (1 point each):**
1 ROA>0 · 2 CFO>0 · 3 ΔROA>0 · 4 CFO/Assets > ROA (cash > accrual earnings) ·
5 Δ(LTD/Assets)<0 (less leverage) · 6 Δ(CurrentRatio)>0 · 7 no new shares ·
8 Δ(GrossMargin)>0 · 9 Δ(AssetTurnover)>0. We also report `max_possible` =
how many were computable (honest partial score).
> Example: a firm with rising ROA, positive cash flow > net income, falling debt,
> improving margin & turnover, no dilution → **F = 7–8 / 9** (high quality).

**Altman Z-score (1968):**
`Z = 1.2·(WC/TA) + 1.4·(RE/TA) + 3.3·(EBIT/TA) + 0.6·(MktCap/TotalLiab) + 1.0·(Sales/TA)`
Zones: **Z > 2.99 safe · 1.81–2.99 grey · < 1.81 distress**.
> Example: WC/TA 0.18, RE/TA 0.45, EBIT/TA 0.18, MktCap/Liab 6.0, Sales/TA 0.9 →
> Z = 0.22+0.63+0.59+3.6+0.9 = **5.9 → safe**. (Calibrated on manufacturers;
> indicative only for banks/REITs.)

---

## 6. Cross-Sectional Scoring  (`models/scoring.py`)

**Winsorize:** clip each feature at its 2nd/98th percentile (tame outliers).
**Robust z-score:** `z = (x − median) / (1.4826 · MAD)`, MAD = median(|x − median|).
Robust to outliers; 1.4826 makes it match std for normal data.
**Sector-neutralize:** z within each sector group (so you compare a bank to banks).
**Composite:** weighted mean of *signed* z-scores (negative weight = "lower is
better", e.g. valuation), normalised by the weight actually present → **percentile
rank 0–100**.
> Example: values [10,12,14,16,50] → median 14, MAD 2, scale 2.965; after
> winsorizing the 50 to ~16, z-scores are ~[−1.35,−0.67,0,+0.67,+0.67]. Two
> features (quality weight +1, cheapness weight −1): a name with quality z=+1.5 and
> cheapness z=−1.0 (i.e. cheap) → score = (1·1.5 + 1·1.0)/2 = **+1.25** → high rank.

---

## 7. Evaluation Metrics  (`validation/metrics.py`)

**Information Coefficient (IC):** Pearson corr(prediction, realized return).
**Rank-IC:** Spearman = Pearson on the ranks (robust; the primary signal metric).
> Example: monthly rank-IC of 0.05 is already a *useful* equity signal; IC of
> identical arrays = 1.0; of a monotone transform, rank-IC = 1.0.

**Hit rate:** fraction where sign(demeaned prediction) = sign(demeaned outcome).
**Brier score:** mean((prob − outcome)²) for probabilistic forecasts (lower better).

**Sharpe:** `R̄ / σ × √periods`.
> Example: mean daily 0.05%, daily σ 1.0% → daily SR 0.05 → **0.79 annualized**.

**Sortino (FIXED):** `R̄ / downside_deviation × √periods` (downside deviation as in §2).
> Example: returns [2%,−1%,3%,−2%], mean 0.5%, downside dev 1.118% → **Sortino 0.447**
> (per-period).

**Probabilistic Sharpe Ratio (Bailey-LdP):** probability the *true* SR exceeds a
benchmark, given sample length, skew, kurtosis:
`PSR = Φ( (SR − SR*)·√(n−1) / √(1 − skew·SR + (kurt−1)/4·SR²) )` (SR per-observation).
> Example: daily SR 0.05 over n=756 (3y), skew 0, kurt 3, SR*=0 → z ≈ 0.05·√755 =
> 1.37 → **PSR ≈ 0.91** (91% confident the SR is really > 0).

**Deflated Sharpe Ratio (Bailey-LdP) — the overfitting guard, edge-case FIXED:**
PSR against a raised benchmark `SR*` = the *expected maximum* SR from N random trials:
`SR* = σ_SR · [ (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)) ]`, γ = Euler-Mascheroni
(0.5772), σ_SR = std of the trials' Sharpes.
> Meaning: "is your Sharpe bigger than the *best you'd expect from luck* after
> trying N things?" More trials → higher bar → lower DSR. Try 200 variants and the
> winner's DSR can be near 0 even if its raw Sharpe looks great — which is exactly
> the trap this catches. (`n_trials=1` now returns plain PSR instead of crashing.)

---

## 8. Leakage-Safe Cross-Validation  (`validation/splits.py`)

**Purged walk-forward:** train only on the past; drop training rows whose label
window [t, t+h] reaches into the test block (purge). Guarantees `train.max() < test.min()`.

**Purged k-fold + embargo:** for a test block [a,b], remove `[a−h, b+embargo]` from
training so no label overlaps and a buffer follows.
> Example: 100 samples, 5 folds, horizon 5, embargo 2. Fold covering test indices
> 20–39 trains on everything EXCEPT indices **15–41** (5 purged before, 2 embargoed
> after). This is what stops the model from "studying tomorrow's answer sheet."

---

## 9. Backtest  (`backtest/engine.py`)

At each rebalance: rank the universe by score into quantiles; go long the top
quantile (and short the bottom, if long/short); portfolio return = `mean(top fwd) −
mean(bottom fwd)`. Turnover = Jaccard change in holdings; cost = turnover × bps.
Report **net Sharpe, mean rank-IC, IC-IR, max drawdown, turnover, cum return** — not
cumulative return alone.
> Example: top decile +1.2%, bottom −0.3% → gross L/S +1.5%; 40% turnover at 10 bps
> → cost 0.04% → **net +1.46%** for that period.

---

## 10. Documented Simplifications & Known Limitations (honesty section)

These are *deliberate, disclosed* choices — not bugs — that a reviewer/upgrade should weigh:
- **Piotroski ROA** uses end-of-year assets; the original uses *beginning*-of-year. Minor; affects 3 signals slightly.
- **Altman EBIT** ≈ operating income (good proxy, not identical).
- **EV** uses long-term debt only (omits short-term/current debt, preferred, minority interest) → understates EV for names with big short-term debt.
- **Amihud** unscaled (ordering-only).
- **Corwin-Schultz spread** overstates for very liquid names (rough upper bound).
- **Betas** are single-window; use `blume_adjust_beta` and/or longer windows for prediction.
- **Rank-IC** ties aren't averaged (fine for continuous data).
- **Backtest** applies cost once to the spread (not per-leg), and — critically —
  runs on a **survivor-biased, small universe** on free data, so any backtest here
  is illustrative of the *machinery*, not a validated edge. Survivorship-free data
  (Sharadar/CRSP) is required before trusting backtest numbers.

## 11. Fitting extras NOT yet added (candidates for the next hardening pass)
GJR-GARCH conditional vol · DCC time-varying correlations · triple-barrier
labels (path-dependent P(target-before-stop)) · Ledoit-Wolf covariance shrinkage ·
market-impact/capacity model · TTM (trailing-twelve-month) fundamentals for cleaner
valuation.
