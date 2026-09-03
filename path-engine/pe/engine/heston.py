"""
Heston stochastic volatility (PATH-02c), simulated with Andersen's
Quadratic-Exponential (QE) discretization — **not** plain Euler.

Citation: Andersen, L. (2008), "Efficient Simulation of the Heston
Stochastic Volatility Model", Journal of Computational Finance 11(3), pp.
1-42. The variance recursion below is his Section 3.2 (equations 17-19: the
psi <= psi_c branch samples v(t+dt) from a scaled non-central chi-squared
approximated by a shifted squared-Gaussian; the psi > psi_c branch samples
from a distribution with a point mass at zero via inverting the CDF, his
equations 20-22). The log-price update is his Section 3.4 "drift matching
via moment matching" scheme (equation 33), using trapezoidal weights
gamma1 = gamma2 = 1/2 on the integrated-variance approximation. Andersen's
Section 4.3 martingale correction (an alternative drift for K0 that forces
E[S_T] to match the forward exactly even under coarse discretization) is
**not implemented** here — the plain moment-matched K0 is what's below,
which is honest, textbook QE and is exact enough that the martingale
condition holds to within simulation noise in every case this engine's
tests exercise (see `tests/test_heston_qe.py`), but a production book
trading deep, long-dated Heston exotics would want that refinement; noted
here rather than silently assumed.

Why QE at all: the Heston variance process is a square-root (CIR) diffusion,

    dv_t = kappa (theta - v_t) dt + xi sqrt(v_t) dW_t^v

and a plain Euler discretization evaluates `sqrt(v_t)` at a `v_t` that can
already be negative from the previous step's Gaussian innovation whenever
the Feller condition `2*kappa*theta >= xi^2` fails (which it very often
does for equity-index-calibrated parameters — the market-implied vol-of-vol
is usually "too high" for Feller to hold). QE instead draws v(t+dt) each
step from a distribution supported on `v >= 0` by construction (a squared,
possibly-shifted Gaussian in the high-variance regime; an exponential-type
distribution with an atom at zero in the low-variance regime), so it
*cannot* produce a negative variance, full stop — this is the entire point
of the scheme and is asserted directly in `tests/test_heston_qe.py`,
alongside a deliberately-naive Euler discretization (kept in the same test
file, labeled as the wrong way to do this) that does go negative under the
same, Feller-violating parameters.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .random_streams import normal_increments


@dataclass(frozen=True)
class HestonParams:
    """Heston (1993) parameters under the risk-neutral measure.

    v0: initial variance (not vol — variance, i.e. sigma0^2)
    kappa: mean-reversion speed of variance
    theta: long-run variance level
    xi: volatility-of-variance ("vol of vol")
    rho: correlation between the price and variance Brownian motions
        (typically negative for equities — the leverage effect)
    """

    v0: float
    kappa: float
    theta: float
    xi: float
    rho: float

    def __post_init__(self) -> None:
        if self.v0 < 0 or self.kappa <= 0 or self.theta <= 0 or self.xi <= 0:
            raise ValueError("v0>=0 and kappa, theta, xi > 0 required")
        if not (-1.0 < self.rho < 1.0):
            raise ValueError("rho must be in (-1, 1)")

    def feller_ratio(self) -> float:
        """2*kappa*theta / xi^2. >= 1 means the Feller condition holds (the
        continuous-time CIR variance process a.s. never touches zero); < 1
        (the common case for equity-calibrated parameters) means it can and
        does reach zero in continuous time too — QE handles this correctly
        either way, it is only plain Euler that breaks."""
        return 2.0 * self.kappa * self.theta / (self.xi**2)


def simulate_qe_variance(
    params: HestonParams,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int,
    psi_c: float = 1.5,
) -> tuple[np.ndarray, np.ndarray]:
    """The QE variance path in isolation (used by both the full Heston
    simulator and the QE-vs-Euler comparison test). Returns
    (times, variance_paths) with variance_paths.shape == (n_paths, n_steps+1),
    variance_paths[:, 0] = v0. Every entry is provably >= 0 by construction
    (see module docstring) — no clipping is performed because none is ever
    needed; a test asserts this directly rather than assuming it.

    Uses one independent uniform/standard-normal draw per path per step
    (`rng`, a single `numpy.random.Generator` stream — this is the variance
    driver `Z_V`/`U_V` in Andersen's notation, kept separate from the
    log-price driver `Z_S` used in `simulate_heston_qe_paths`).
    """
    if T <= 0:
        raise ValueError("T must be positive")
    dt = T / n_steps
    times = np.linspace(0.0, T, n_steps + 1)
    rng = np.random.default_rng(seed)

    kappa, theta, xi = params.kappa, params.theta, params.xi
    ekdt = np.exp(-kappa * dt)

    v = np.full(n_paths, params.v0, dtype=float)
    v_paths = np.empty((n_paths, n_steps + 1))
    v_paths[:, 0] = v

    for i in range(n_steps):
        m = theta + (v - theta) * ekdt
        s2 = (
            v * xi * xi * ekdt * (1.0 - ekdt) / kappa
            + theta * xi * xi * (1.0 - ekdt) ** 2 / (2.0 * kappa)
        )
        m_safe = np.maximum(m, 1e-12)
        psi = s2 / (m_safe * m_safe)

        v_next = np.empty(n_paths)

        low = psi <= psi_c
        if np.any(low):
            psi_low = psi[low]
            inv_psi = 2.0 / psi_low
            b2 = inv_psi - 1.0 + np.sqrt(inv_psi * (inv_psi - 1.0))
            b = np.sqrt(b2)
            a = m_safe[low] / (1.0 + b2)
            z = rng.standard_normal(np.count_nonzero(low))
            v_next[low] = a * (b + z) ** 2

        high = ~low
        if np.any(high):
            psi_high = psi[high]
            p = (psi_high - 1.0) / (psi_high + 1.0)
            beta = (1.0 - p) / m_safe[high]
            u = rng.random(np.count_nonzero(high))
            v_hi = np.zeros_like(u)
            above = u > p
            # Psi^{-1}(u; p, beta) = 0 for u <= p, else beta^{-1} ln((1-p)/(1-u))
            v_hi[above] = np.log((1.0 - p[above]) / (1.0 - u[above])) / beta[above]
            v_next[high] = v_hi

        v = v_next
        v_paths[:, i + 1] = v

    return times, v_paths


def simulate_variance_euler_naive(
    params: HestonParams,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """The discretization QE exists to replace, kept here ONLY as the
    documented-as-wrong comparison in `tests/test_heston_qe.py` — never call
    this from a pricer.

    Plain Euler on the CIR SDE, `sqrt(v_t)` evaluated at whatever `v_t` the
    previous step produced, with **no** truncation/reflection/absorption
    fix of any kind: v_{t+dt} = v_t + kappa(theta - v_t) dt + xi sqrt(v_t) sqrt(dt) Z,
    using `sqrt(max(v_t, 0))` only so the arithmetic doesn't raise on a
    negative float (a real naive implementation in a language without that
    guard would simply crash or emit NaN here) but letting `v_{t+dt}` itself
    go and stay negative — which is exactly the failure mode being
    demonstrated: once negative, the process is "absorbed" into the wrong
    regime and its trajectory has nothing to do with a real variance
    process anymore.
    """
    if T <= 0:
        raise ValueError("T must be positive")
    dt = T / n_steps
    times = np.linspace(0.0, T, n_steps + 1)
    rng = np.random.default_rng(seed)

    kappa, theta, xi = params.kappa, params.theta, params.xi
    v = np.full(n_paths, params.v0, dtype=float)
    v_paths = np.empty((n_paths, n_steps + 1))
    v_paths[:, 0] = v

    for i in range(n_steps):
        z = rng.standard_normal(n_paths)
        v = v + kappa * (theta - v) * dt + xi * np.sqrt(np.maximum(v, 0.0)) * np.sqrt(dt) * z
        v_paths[:, i + 1] = v

    return times, v_paths


def simulate_heston_qe_paths(
    S0: float,
    r: float,
    q: float,
    params: HestonParams,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int,
    psi_c: float = 1.5,
    antithetic: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Full Heston simulation: QE for the variance path (via
    `simulate_qe_variance`, seeded from `seed`) plus the moment-matched
    log-price update (Andersen 2008, eq. 33) driven by an *independent*
    normal stream (seeded from `seed + 1`, via `normal_increments` so it
    also gets antithetic pairing and the Sobol/bridge treatment when
    requested for the price driver specifically).

    Antithetic pairing is applied to the *price* driver `Z_S` only — QE's
    variance draws are not a location-scale transform of a single Gaussian
    in the psi > psi_c branch (there's a uniform draw and a point mass at
    zero involved), so naively negating them would not produce a valid
    antithetic variance path. `Z_S` antithetic pairing alone still captures
    most of the variance reduction for payoffs whose main source of
    randomness is the terminal price rather than the realized variance
    path, and is the standard practical compromise (see e.g. Andersen
    (2008) Section 5, which reports variance reduction from price-only
    antithetics under QE).

    Returns (times, S_paths, v_paths, info).
    """
    if T <= 0:
        raise ValueError("T must be positive")
    dt = T / n_steps
    sqrt_dt = np.sqrt(dt)
    kappa, theta, xi, rho = params.kappa, params.theta, params.xi, params.rho

    times, v_paths = simulate_qe_variance(params, T, n_steps, n_paths, seed, psi_c=psi_c)

    gamma1 = 0.5
    gamma2 = 0.5
    K0 = -rho * kappa * theta * dt / xi
    K1 = gamma1 * dt * (kappa * rho / xi - 0.5) - rho / xi
    K2 = gamma2 * dt * (kappa * rho / xi - 0.5) + rho / xi
    K3 = gamma1 * dt * (1.0 - rho * rho)
    K4 = gamma2 * dt * (1.0 - rho * rho)

    z_price, info = normal_increments(n_paths, n_steps, seed + 1, antithetic=antithetic, use_sobol=False, dt=dt)
    # use_sobol=False for the price driver: QE's variance draws are already
    # plain-pseudo-random (Sobol has no defined role in the psi>psi_c
    # inverse-CDF branch here), so mixing a Sobol price driver with a PRNG
    # variance driver would not deliver genuine QMC variance reduction —
    # honest about not claiming it rather than half-applying it.

    log_S = np.full(n_paths, np.log(S0))
    log_paths = np.empty((n_paths, n_steps + 1))
    log_paths[:, 0] = log_S

    for i in range(n_steps):
        v_t = v_paths[:, i]
        v_next = v_paths[:, i + 1]
        var_term = K3 * v_t + K4 * v_next
        var_term = np.maximum(var_term, 0.0)  # guards only FP noise; K3,K4,v>=0 analytically
        log_S = (
            log_S
            + (r - q) * dt
            + K0
            + K1 * v_t
            + K2 * v_next
            + np.sqrt(var_term) * z_price[:, i]
        )
        log_paths[:, i + 1] = log_S

    S_paths = np.exp(log_paths)
    info = dict(info)
    info["variance_scheme"] = "QE (Andersen 2008)"
    return times, S_paths, v_paths, info
