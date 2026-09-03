"""
Closed-form reference prices under flat-vol GBM. These exist for exactly one
reason: to check the Monte Carlo engine against something that isn't itself
Monte Carlo. Every function here is used from `pe/validation` and/or as a
control variate; none of them is a general-purpose pricing library — this
engine's business is path-dependent payoffs that generally do *not* have
closed forms, which is the entire reason it exists.

Formulas and citations:
    - Black-Scholes-Merton vanilla call/put: Black & Scholes (1973);
      Merton (1973) for the continuous dividend/cost-of-carry extension.
    - Geometric-average Asian option (discrete fixings) closed form:
      Kemna & Vorst (1990), "A pricing method for options based on average
      asset values", Journal of Banking & Finance 14(1). The discrete
      geometric average of a GBM is itself lognormal, so the same BS
      machinery applies with an adjusted volatility and drift.
    - Continuous single-barrier options: Reiner & Rubinstein (1991),
      "Breaking Down the Barriers", Risk Magazine 4(8); restated in the
      standard reference table form used here in Haug, E.G., "The Complete
      Guide to Option Pricing Formulas" (2nd ed., 2007), Chapter 4. Rebates
      are not implemented (fixed at 0) — with no rebate, knock-in + knock-out
      = vanilla is a model-free identity, which lets `barrier_price_bs`
      derive every "out" price as vanilla minus the corresponding "in"
      price instead of re-deriving the (rebate-bearing) E/F terms, and lets
      the test suite check that identity directly as an independent
      sanity check on top of the numeric values themselves.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.stats import norm

OptionType = Literal["call", "put"]
BarrierDirection = Literal["up", "down"]
BarrierKind = Literal["in", "out"]


def bs_price(
    S0: float,
    K: float,
    r: float,
    q: float,
    sigma: float,
    T: float,
    option_type: OptionType = "call",
) -> float:
    """Black-Scholes-Merton price with continuous dividend yield q."""
    if T <= 0:
        intrinsic = max(S0 - K, 0.0) if option_type == "call" else max(K - S0, 0.0)
        return intrinsic
    if sigma <= 0:
        fwd = S0 * np.exp((r - q) * T)
        disc = np.exp(-r * T)
        intrinsic = max(fwd - K, 0.0) if option_type == "call" else max(K - fwd, 0.0)
        return disc * intrinsic
    d1 = (np.log(S0 / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S0 * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif option_type == "put":
        return K * np.exp(-r * T) * norm.cdf(-d2) - S0 * np.exp(-q * T) * norm.cdf(-d1)
    raise ValueError(f"unknown option_type {option_type!r}")


def geometric_asian_price_bs(
    S0: float,
    K: float,
    r: float,
    q: float,
    sigma: float,
    T: float,
    n_fixings: int,
    option_type: OptionType = "call",
) -> float:
    """Closed-form price of a fixed-strike, discretely-monitored geometric-
    average Asian option under GBM (Kemna & Vorst, 1990). Fixings assumed
    equally spaced at t_i = i*T/n, i=1..n_fixings (the average includes the
    terminal fixing, not t=0).
    """
    n = n_fixings
    sigma_g2 = sigma * sigma * (n + 1) * (2 * n + 1) / (6 * n * n)
    mu_g = (r - q - 0.5 * sigma * sigma) * (n + 1) / (2 * n) + 0.5 * sigma_g2
    sigma_g = np.sqrt(sigma_g2)
    if T <= 0:
        return max(S0 - K, 0.0) if option_type == "call" else max(K - S0, 0.0)
    d1 = (np.log(S0 / K) + (mu_g + 0.5 * sigma_g2) * T) / (sigma_g * np.sqrt(T))
    d2 = d1 - sigma_g * np.sqrt(T)
    fwd_g = S0 * np.exp(mu_g * T)
    if option_type == "call":
        return np.exp(-r * T) * (fwd_g * norm.cdf(d1) - K * norm.cdf(d2))
    elif option_type == "put":
        return np.exp(-r * T) * (K * norm.cdf(-d2) - fwd_g * norm.cdf(-d1))
    raise ValueError(f"unknown option_type {option_type!r}")


def _barrier_in_price(
    S: float, K: float, H: float, r: float, q: float, sigma: float, T: float,
    option_type: OptionType, direction: BarrierDirection,
) -> float:
    b = r - q
    phi = 1.0 if option_type == "call" else -1.0
    eta = 1.0 if direction == "down" else -1.0

    mu = (b - 0.5 * sigma * sigma) / (sigma * sigma)
    lam = np.sqrt(mu * mu + 2.0 * r / (sigma * sigma))
    sT = sigma * np.sqrt(T)

    x1 = np.log(S / K) / sT + (1 + mu) * sT
    x2 = np.log(S / H) / sT + (1 + mu) * sT
    y1 = np.log(H * H / (S * K)) / sT + (1 + mu) * sT
    y2 = np.log(H / S) / sT + (1 + mu) * sT

    def A():
        return phi * S * np.exp((b - r) * T) * norm.cdf(phi * x1) - phi * K * np.exp(-r * T) * norm.cdf(phi * x1 - phi * sT)

    def B():
        return phi * S * np.exp((b - r) * T) * norm.cdf(phi * x2) - phi * K * np.exp(-r * T) * norm.cdf(phi * x2 - phi * sT)

    def C():
        return phi * S * np.exp((b - r) * T) * (H / S) ** (2 * (mu + 1)) * norm.cdf(eta * y1) - \
            phi * K * np.exp(-r * T) * (H / S) ** (2 * mu) * norm.cdf(eta * y1 - eta * sT)

    def D():
        return phi * S * np.exp((b - r) * T) * (H / S) ** (2 * (mu + 1)) * norm.cdf(eta * y2) - \
            phi * K * np.exp(-r * T) * (H / S) ** (2 * mu) * norm.cdf(eta * y2 - eta * sT)

    if option_type == "call":
        if direction == "down":
            return C() if K > H else A() - B() + D()
        else:  # up
            return A() if K > H else B() - C() + D()
    else:  # put
        if direction == "down":
            return B() - C() + D() if K > H else A()
        else:  # up
            return A() - B() + D() if K > H else C()


def barrier_price_bs(
    S0: float,
    K: float,
    H: float,
    r: float,
    q: float,
    sigma: float,
    T: float,
    option_type: OptionType,
    direction: BarrierDirection,
    kind: BarrierKind,
) -> float:
    """Continuous-monitoring single-barrier option price under flat-vol GBM,
    zero rebate (Reiner & Rubinstein 1991 / Haug Ch. 4 — see module
    docstring). `direction` is where the barrier sits relative to spot
    ("up" => H > S0, "down" => H < S0 is the sensible regime; the formula
    is evaluated as given regardless, so a nonsensical combination — e.g. an
    "up" barrier already breached at inception — is the caller's mistake to
    avoid, not something this function guards against).
    """
    in_price = _barrier_in_price(S0, K, H, r, q, sigma, T, option_type, direction)
    if kind == "in":
        return in_price
    vanilla = bs_price(S0, K, r, q, sigma, T, option_type)
    return vanilla - in_price
